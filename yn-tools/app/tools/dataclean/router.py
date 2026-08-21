"""データクリーニングツール - ルーター"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
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
from .models import DataCleanJob

router = APIRouter(prefix="/tools/dataclean", tags=["dataclean"])
templates = make_templates("app/templates")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# ===== ページルート =====

@router.get("/", response_class=HTMLResponse)
async def dataclean_index(
    request: Request,
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """ダッシュボード（処理履歴一覧）"""
    result = await db.execute(
        select(DataCleanJob)
        .where(DataCleanJob.user_id == user.id)
        .order_by(DataCleanJob.created_at.desc())
        .limit(20)
    )
    jobs = result.scalars().all()

    # テンプレート向けに options_list を付与
    for job in jobs:
        try:
            job.options_list = json.loads(job.options_applied or "[]")
        except Exception:
            job.options_list = []

    monthly_used = await get_monthly_usage(db, user.id, "dataclean")

    return templates.TemplateResponse(
        request, "tools/dataclean/index.html", {
            "user": user,
            "page": "dataclean",
            "view": "dashboard",
            "jobs": jobs,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("dataclean"),
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def dataclean_new(
    request: Request,
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """ステップUI（新規クリーニング）"""
    monthly_used = await get_monthly_usage(db, user.id, "dataclean")

    return templates.TemplateResponse(
        request, "tools/dataclean/index.html", {
            "user": user,
            "page": "dataclean",
            "view": "new",
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("dataclean"),
        }
    )


@router.get("/{job_id}/result", response_class=HTMLResponse)
async def dataclean_result(
    job_id: int,
    request: Request,
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """差分プレビュー・ダウンロード画面"""
    result = await db.execute(
        select(DataCleanJob).where(
            DataCleanJob.id == job_id,
            DataCleanJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return RedirectResponse(url="/tools/dataclean/", status_code=303)

    # 差分プレビューHTML生成（ファイルが残っていれば）
    diff_html = ""
    if job.status == "done":
        upload = service.load_upload(user.id, job_id)
        if upload:
            raw, ext = upload
            try:
                import pandas as pd

                df_before = service.read_file(raw, f"upload{ext}")
                options = json.loads(job.options_applied or "[]")
                df_after, _ = service.apply_cleaning(df_before, options)

                # dedup key_col は保存していないので全列で適用（差分表示のみ）
                diff_html = service.make_diff_html(df_before, df_after)
            except Exception:
                diff_html = "<p class='text-gray-400 text-sm'>差分プレビューを生成できませんでした。</p>"

    monthly_used = await get_monthly_usage(db, user.id, "dataclean")

    try:
        job_options_list = json.loads(job.options_applied or "[]")
    except Exception:
        job_options_list = []

    return templates.TemplateResponse(
        request, "tools/dataclean/index.html", {
            "user": user,
            "page": "dataclean",
            "view": "result",
            "job": job,
            "diff_html": diff_html,
            "job_options_list": job_options_list,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("dataclean"),
        }
    )


# ===== APIエンドポイント =====

@router.post("/api/upload")
async def api_upload(
    request: Request,
    file: UploadFile,
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """ファイルアップロード → プレビューHTML + カラム一覧 返却"""
    if not file or not file.filename:
        return {"error": "ファイルが選択されていません。"}

    ext = Path(file.filename).suffix.lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        return {"error": "CSV（.csv）またはExcel（.xlsx/.xls）ファイルをアップロードしてください。"}

    data = await file.read()

    if len(data) == 0:
        return {"error": "ファイルが空です。"}

    if len(data) > MAX_FILE_SIZE:
        return {"error": "ファイルサイズが上限（10MB）を超えています。"}

    # 利用上限チェック
    used = await get_monthly_usage(db, user.id, "dataclean")
    if err := limit_error("dataclean", used, get_limit("dataclean")):
        return {"error": err}

    try:
        df = service.read_file(data, file.filename)
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"ファイルの読み込みに失敗しました: {str(e)}"}

    if df.empty:
        return {"error": "データが存在しません（空のファイルです）。"}

    # DBにジョブレコード作成（pending）
    job = DataCleanJob(
        user_id=user.id,
        original_filename=file.filename,
        file_size_bytes=len(data),
        row_count_before=len(df),
        col_count=len(df.columns),
        options_applied="[]",
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # 一時ファイル保存
    service.save_upload(user.id, job.id, data, ext)

    # プレビューHTML
    preview_html = service.make_preview_html(df)
    encoding = service.detect_encoding(data) if ext == ".csv" else "xlsx"

    return {
        "job_id": job.id,
        "columns": list(df.columns),
        "preview_html": preview_html,
        "row_count": len(df),
        "encoding": encoding,
    }


class ExecuteRequest(BaseModel):
    options: list[str] = []
    dedup_key_col: str | None = None


@router.post("/api/{job_id}/execute")
async def api_execute(
    job_id: int,
    body: ExecuteRequest,
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """クリーニング実行"""
    result = await db.execute(
        select(DataCleanJob).where(
            DataCleanJob.id == job_id,
            DataCleanJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "ジョブが見つかりません。"}

    if job.status == "done":
        return {"error": "このジョブはすでに処理済みです。"}

    upload = service.load_upload(user.id, job_id)
    if not upload:
        return {"error": "アップロードファイルが見つかりません。再度アップロードしてください。"}

    raw, ext = upload

    try:
        df_before = service.read_file(raw, f"upload{ext}")
    except Exception as e:
        job.status = "error"
        job.error_message = str(e)
        await db.commit()
        return {"error": f"ファイルの読み込みに失敗しました: {str(e)}"}

    try:
        df_after, changed_cells = service.apply_cleaning(
            df_before, body.options, body.dedup_key_col
        )
    except Exception as e:
        job.status = "error"
        job.error_message = str(e)
        await db.commit()
        return {"error": f"クリーニング処理に失敗しました: {str(e)}"}

    # 出力ファイル保存
    try:
        out_path = service.save_output(user.id, job_id, df_after, fmt="csv")
    except Exception as e:
        job.status = "error"
        job.error_message = str(e)
        await db.commit()
        return {"error": f"出力ファイルの保存に失敗しました: {str(e)}"}

    # DBアップデート
    job.row_count_after = len(df_after)
    job.col_count = len(df_after.columns)
    job.changed_cells = changed_cells
    job.options_applied = json.dumps(body.options, ensure_ascii=False)
    job.output_path = str(out_path)
    job.status = "done"
    await db.commit()

    return {
        "changed_cells": changed_cells,
        "row_before": job.row_count_before,
        "row_after": len(df_after),
        "redirect_url": f"/tools/dataclean/{job_id}/result",
    }


@router.get("/api/{job_id}/download")
async def api_download(
    job_id: int,
    fmt: str = "csv",
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """クリーン済みファイルダウンロード"""
    result = await db.execute(
        select(DataCleanJob).where(
            DataCleanJob.id == job_id,
            DataCleanJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job or job.status != "done":
        return {"error": "ダウンロード可能なファイルがありません。"}

    upload = service.load_upload(user.id, job_id)
    if not upload:
        return {"error": "元ファイルが見つかりません。"}

    raw, ext = upload
    try:
        df_before = service.read_file(raw, f"upload{ext}")
    except Exception as e:
        return {"error": str(e)}

    options = json.loads(job.options_applied or "[]")
    try:
        df_after, _ = service.apply_cleaning(df_before, options)
    except Exception as e:
        return {"error": str(e)}

    # 最新状態のファイルを生成してダウンロード
    if fmt == "xlsx":
        out_path = service.save_output(user.id, job_id, df_after, fmt="xlsx")
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        dl_name = Path(job.original_filename).stem + "_clean.xlsx"
    else:
        out_path = service.save_output(user.id, job_id, df_after, fmt="csv")
        media_type = "text/csv; charset=utf-8"
        dl_name = Path(job.original_filename).stem + "_clean.csv"

    return FileResponse(
        path=str(out_path),
        media_type=media_type,
        filename=dl_name,
    )


@router.delete("/api/{job_id}")
async def api_delete(
    job_id: int,
    user: User = Depends(require_tool_access("dataclean")),
    db: AsyncSession = Depends(get_db),
):
    """ジョブ削除（DBレコード + 一時ファイル）"""
    result = await db.execute(
        select(DataCleanJob).where(
            DataCleanJob.id == job_id,
            DataCleanJob.user_id == user.id,
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
