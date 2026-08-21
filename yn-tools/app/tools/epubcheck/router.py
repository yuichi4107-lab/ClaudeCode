"""EPUBバリデーター - ルーター"""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User
from app.tools.epubcheck.validator import validate_epub

router = APIRouter(prefix="/tools/epubcheck", tags=["epubcheck"])
templates = make_templates("app/templates")

MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("epubcheck")),
):
    return templates.TemplateResponse(
        request, "tools/epubcheck/index.html",
        {"user": user, "page": "epubcheck"},
    )


@router.post("/api/validate")
async def api_validate(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(require_tool_access("epubcheck")),
):
    """
    EPUBファイルをアップロードしてバリデーション結果をJSONで返す。
    ファイルはメモリ上のみで処理し、ディスクには書き込まない。
    """
    # 拡張子チェック
    filename = file.filename or ""
    if not filename.lower().endswith(".epub"):
        raise HTTPException(
            status_code=400,
            detail="EPUB ファイル(.epub)のみアップロード可能です",
        )

    # Content-Length による事前チェック（ヘッダーがある場合）
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            cl = int(content_length)
            if cl > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail="ファイルサイズが500MBを超えています",
                )
        except ValueError:
            pass

    # ファイル全体をメモリに読み込む
    try:
        file_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ファイルの読み込みに失敗しました: {e}")

    # サイズ二重チェック（読み込み後）
    if len(file_bytes) > MAX_FILE_SIZE:
        del file_bytes
        raise HTTPException(
            status_code=413,
            detail="ファイルサイズが500MBを超えています",
        )

    # バリデーション実行
    try:
        result = validate_epub(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"バリデーション処理でエラーが発生しました: {e}")
    finally:
        # メモリ解放（GCに依存しない明示的 del）
        del file_bytes

    return JSONResponse(content=result)
