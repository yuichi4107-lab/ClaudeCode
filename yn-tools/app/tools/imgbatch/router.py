"""画像一括加工ツール - ルーター"""

import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.tools.usage_limit import get_limit, get_monthly_usage, limit_error
from app.users.models import User

from . import service
from .models import ImgBatchJob
from .service import SNS_PRESET_LABELS, SNS_PRESETS

router = APIRouter(prefix="/tools/imgbatch", tags=["imgbatch"])
templates = make_templates("app/templates")

MAX_FILE_SIZE = service.MAX_FILE_SIZE
MAX_FILES = service.MAX_FILES


# ===== ページルート =====

@router.get("/", response_class=HTMLResponse)
async def imgbatch_index(
    request: Request,
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """ダッシュボード（バッチ処理履歴一覧）"""
    result = await db.execute(
        select(ImgBatchJob)
        .where(ImgBatchJob.user_id == user.id)
        .order_by(ImgBatchJob.created_at.desc())
        .limit(20)
    )
    jobs = result.scalars().all()

    # preset_names をリストに変換
    for job in jobs:
        try:
            job.preset_list = json.loads(job.preset_names or "[]")
        except Exception:
            job.preset_list = []

    monthly_used = await get_monthly_usage(db, user.id, "imgbatch")

    return templates.TemplateResponse(
        request, "tools/imgbatch/index.html", {
            "user": user,
            "page": "imgbatch",
            "view": "dashboard",
            "jobs": jobs,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("imgbatch"),
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def imgbatch_new(
    request: Request,
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """処理設定画面（アップロード+設定）"""
    monthly_used = await get_monthly_usage(db, user.id, "imgbatch")

    return templates.TemplateResponse(
        request, "tools/imgbatch/index.html", {
            "user": user,
            "page": "imgbatch",
            "view": "new",
            "sns_presets": SNS_PRESET_LABELS,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("imgbatch"),
        }
    )


@router.get("/{job_id}/result", response_class=HTMLResponse)
async def imgbatch_result(
    job_id: int,
    request: Request,
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """結果プレビュー・ZIPダウンロード画面"""
    result = await db.execute(
        select(ImgBatchJob).where(
            ImgBatchJob.id == job_id,
            ImgBatchJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/tools/imgbatch/", status_code=303)

    thumbnails = []
    if job.status == "done":
        thumbnails = service.get_output_thumbnails(user.id, job_id)

    try:
        job.preset_list = json.loads(job.preset_names or "[]")
    except Exception:
        job.preset_list = []

    monthly_used = await get_monthly_usage(db, user.id, "imgbatch")

    return templates.TemplateResponse(
        request, "tools/imgbatch/index.html", {
            "user": user,
            "page": "imgbatch",
            "view": "result",
            "job": job,
            "thumbnails": thumbnails,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("imgbatch"),
        }
    )


# ===== APIエンドポイント =====

@router.post("/api/upload")
async def api_upload(
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """複数画像アップロード → job_id + サムネイルURL返却"""
    if not files:
        return {"error": "ファイルが選択されていません。"}

    if len(files) > MAX_FILES:
        return {"error": f"アップロードは最大{MAX_FILES}枚までです。"}

    # 利用上限チェック
    used = await get_monthly_usage(db, user.id, "imgbatch")
    if err := limit_error("imgbatch", used, get_limit("imgbatch")):
        return {"error": err}

    # DBにジョブレコード作成
    job = ImgBatchJob(
        user_id=user.id,
        mode="pending",
        status="pending",
        input_file_count=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # ファイル検証・保存
    files_data: list[tuple[str, bytes]] = []
    thumbnails: list[dict] = []
    errors: list[str] = []

    for upload_file in files:
        if not upload_file.filename:
            continue

        ext = Path(upload_file.filename).suffix.lower()
        if ext not in service.SUPPORTED_EXTENSIONS:
            errors.append(f"{upload_file.filename}: 対応していない形式です（JPG/PNG/WebP/AVIF/GIF）")
            continue

        data = await upload_file.read()

        if len(data) == 0:
            errors.append(f"{upload_file.filename}: ファイルが空です。")
            continue

        if len(data) > MAX_FILE_SIZE:
            errors.append(f"{upload_file.filename}: ファイルサイズが上限（20MB）を超えています。")
            continue

        files_data.append((upload_file.filename, data))
        thumb = service.make_thumbnail_data_url(data, ext)
        size_kb = round(len(data) / 1024, 1)
        thumbnails.append({
            "filename": upload_file.filename,
            "size_kb": size_kb,
            "thumbnail": thumb,
        })

    if not files_data:
        await db.delete(job)
        await db.commit()
        return {"error": "有効なファイルがありません。" + (" " + "; ".join(errors) if errors else "")}

    # ファイル保存
    service.save_input_files(user.id, job.id, files_data)

    # ジョブ更新
    job.input_file_count = len(files_data)
    await db.commit()

    return {
        "job_id": job.id,
        "file_count": len(files_data),
        "thumbnails": thumbnails,
        "errors": errors,
    }


class ProcessRequest(BaseModel):
    mode: str
    presets: list[str] | None = None
    custom_w: int | None = None
    custom_h: int | None = None
    output_format: str | None = None


@router.post("/api/{job_id}/process")
async def api_process(
    job_id: int,
    body: ProcessRequest,
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """画像処理実行"""
    result = await db.execute(
        select(ImgBatchJob).where(
            ImgBatchJob.id == job_id,
            ImgBatchJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "ジョブが見つかりません。"}

    if job.status == "done":
        return {"error": "このジョブはすでに処理済みです。"}

    # ジョブ情報更新
    job.mode = body.mode
    job.preset_names = json.dumps(body.presets or [], ensure_ascii=False)
    job.custom_width = body.custom_w
    job.custom_height = body.custom_h
    job.output_format = body.output_format
    job.status = "processing"
    await db.commit()

    import asyncio

    try:
        loop = asyncio.get_event_loop()
        output_count, zip_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: service.run_batch(
                    user_id=user.id,
                    job_id=job_id,
                    mode=body.mode,
                    preset_names=body.presets,
                    custom_w=body.custom_w,
                    custom_h=body.custom_h,
                    output_format=body.output_format,
                ),
            ),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        job.status = "error"
        job.error_message = "処理がタイムアウトしました（120秒制限）。ファイル数や解像度を減らしてください。"
        await db.commit()
        return {"error": job.error_message}
    except Exception as e:
        job.status = "error"
        job.error_message = str(e)
        await db.commit()
        return {"error": str(e)}

    job.output_file_count = output_count
    job.zip_path = zip_path
    job.status = "done"
    await db.commit()

    return {
        "output_count": output_count,
        "redirect_url": f"/tools/imgbatch/{job_id}/result",
    }


@router.get("/api/{job_id}/download")
async def api_download(
    job_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """ZIPファイルダウンロード（ダウンロード後に一時ファイルを自動削除）"""
    result = await db.execute(
        select(ImgBatchJob).where(
            ImgBatchJob.id == job_id,
            ImgBatchJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job or job.status != "done":
        return {"error": "ダウンロード可能なファイルがありません。"}

    if not job.zip_path or not Path(job.zip_path).exists():
        return {"error": "ZIPファイルが見つかりません。再度処理を実行してください。"}

    zip_path = job.zip_path
    background_tasks.add_task(service.delete_job_files, user.id, job_id)

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=f"imgbatch_{job_id}.zip",
    )


@router.delete("/api/{job_id}")
async def api_delete(
    job_id: int,
    user: User = Depends(require_tool_access("imgbatch")),
    db: AsyncSession = Depends(get_db),
):
    """ジョブ削除（DBレコード + 一時ファイル）"""
    result = await db.execute(
        select(ImgBatchJob).where(
            ImgBatchJob.id == job_id,
            ImgBatchJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "ジョブが見つかりません。"}

    # 一時ファイル削除
    service.delete_job_files(user.id, job_id)

    await db.delete(job)
    await db.commit()

    return {"ok": True}
