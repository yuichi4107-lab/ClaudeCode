"""契約書・利用規約自動作成ツール - ルーター"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from app.core.templates import make_templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import LegalDocument
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/legalgen", tags=["legalgen"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def legalgen_index(
    request: Request,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """契約書自動作成ツール ダッシュボード"""
    result = await db.execute(
        select(LegalDocument)
        .where(LegalDocument.user_id == user.id)
        .order_by(LegalDocument.created_at.desc())
        .limit(20)
    )
    documents = result.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "legalgen")

    return templates.TemplateResponse(
        request, "tools/legalgen/index.html", {
            "user": user,
            "page": "legalgen",
            "view": "dashboard",
            "documents": documents,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("legalgen"),
            "doc_types": service.DOC_TYPES,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def legalgen_new(
    request: Request,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """新規作成フォーム"""
    monthly_used = await get_monthly_usage(db, user.id, "legalgen")

    return templates.TemplateResponse(
        request, "tools/legalgen/index.html", {
            "user": user,
            "page": "legalgen",
            "view": "new",
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("legalgen"),
            "doc_types": service.DOC_TYPES,
        }
    )


@router.get("/api/{doc_id}/download")
async def api_download(
    doc_id: int,
    format: str,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """Word/PDFダウンロード"""
    result = await db.execute(
        select(LegalDocument).where(
            LegalDocument.id == doc_id,
            LegalDocument.user_id == user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return Response(content=json.dumps({"error": "文書が見つかりません"}), media_type="application/json", status_code=404)

    # 編集済みテキストがあれば優先
    text = doc.edited_text or doc.generated_text
    # 常に免責文言を先頭に保証
    text = service.ensure_disclaimer(text)

    if format == "docx":
        try:
            docx_bytes = service.build_docx(text)
        except ImportError as e:
            return Response(
                content=json.dumps({"error": str(e)}),
                media_type="application/json",
                status_code=503,
            )
        filename = f"{doc.title}.docx"
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    elif format == "pdf":
        try:
            pdf_bytes = service.build_pdf(text)
        except ImportError as e:
            return Response(
                content=json.dumps({"error": str(e)}),
                media_type="application/json",
                status_code=503,
            )
        filename = f"{doc.title}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return Response(
        content=json.dumps({"error": "不正なフォーマット指定です（docx または pdf）"}),
        media_type="application/json",
        status_code=400,
    )


@router.get("/{doc_id}", response_class=HTMLResponse)
async def legalgen_detail(
    doc_id: int,
    request: Request,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """生成結果・編集画面"""
    result = await db.execute(
        select(LegalDocument).where(
            LegalDocument.id == doc_id,
            LegalDocument.user_id == user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return RedirectResponse(url="/tools/legalgen/", status_code=303)

    monthly_used = await get_monthly_usage(db, user.id, "legalgen")

    # 入力パラメータをJSONからデシリアライズ
    input_params = {}
    try:
        input_params = json.loads(doc.input_params)
    except Exception:
        pass

    display_text = doc.edited_text or doc.generated_text or ""
    # 常に免責文言を先頭に保証
    display_text = service.ensure_disclaimer(display_text)

    return templates.TemplateResponse(
        request, "tools/legalgen/index.html", {
            "user": user,
            "page": "legalgen",
            "view": "detail",
            "doc": doc,
            "input_params": input_params,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("legalgen"),
            "doc_types": service.DOC_TYPES,
            "display_text": display_text,
            "disclaimer": service.DISCLAIMER,
        }
    )


@router.post("/api/generate")
async def api_generate(
    request: Request,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
    doc_type: str = Form(...),
    party_a_name: str = Form(...),
    party_b_name: str = Form(...),
    effective_date: str = Form(default=""),
    governing_law: str = Form(default="日本法"),
    jurisdiction: str = Form(default="東京地方裁判所"),
    # commission
    work_content: str = Form(default=""),
    compensation: str = Form(default=""),
    ip_ownership: str = Form(default=""),
    # nda
    purpose: str = Form(default=""),
    info_scope: str = Form(default=""),
    # sale
    product_name: str = Form(default=""),
    amount: str = Form(default=""),
    delivery_conditions: str = Form(default=""),
    # tos
    service_name: str = Form(default=""),
    prohibited_items: str = Form(default=""),
    disclaimer_text: str = Form(default="", alias="disclaimer"),
    # privacy
    collected_info: str = Form(default=""),
    usage_purpose: str = Form(default=""),
    contact_info: str = Form(default=""),
    # employment
    salary: str = Form(default=""),
    work_location: str = Form(default=""),
    # rent
    property_name: str = Form(default="", alias="property"),
    rent: str = Form(default=""),
    deposit: str = Form(default=""),
    # 共通（period は複数ツールで使用）
    period: str = Form(default=""),
):
    """AI生成API"""
    used = await get_monthly_usage(db, user.id, "legalgen")
    if err := limit_error("legalgen", used, get_limit("legalgen")):
        return {"error": err}

    params = {
        "doc_type": doc_type,
        "party_a_name": party_a_name,
        "party_b_name": party_b_name,
        "effective_date": effective_date,
        "governing_law": governing_law,
        "jurisdiction": jurisdiction,
        "work_content": work_content,
        "compensation": compensation,
        "ip_ownership": ip_ownership,
        "purpose": purpose,
        "info_scope": info_scope,
        "period": period,
        "product_name": product_name,
        "amount": amount,
        "delivery_conditions": delivery_conditions,
        "service_name": service_name,
        "prohibited_items": prohibited_items,
        "disclaimer": disclaimer_text,
        "collected_info": collected_info,
        "usage_purpose": usage_purpose,
        "contact_info": contact_info,
        "salary": salary,
        "work_location": work_location,
        "property": property_name,
        "rent": rent,
        "deposit": deposit,
    }

    try:
        generated_text = await service.generate_legal_document(doc_type, params)
    except Exception as e:
        return {"error": f"AI生成に失敗しました: {str(e)}"}

    # タイトル自動生成
    doc_info = service.DOC_TYPES.get(doc_type, {})
    doc_name = doc_info.get("name", doc_type)
    month_str = datetime.now().strftime("%Y-%m")
    title = f"{doc_name}_{party_a_name}_{month_str}"

    legal_doc = LegalDocument(
        user_id=user.id,
        doc_type=doc_type,
        title=title,
        party_a_name=party_a_name,
        party_b_name=party_b_name,
        effective_date=effective_date or None,
        input_params=json.dumps(params, ensure_ascii=False),
        generated_text=generated_text,
    )
    db.add(legal_doc)
    await db.commit()
    await db.refresh(legal_doc)

    return {"id": legal_doc.id, "generated_text": generated_text}


class SaveRequest(BaseModel):
    edited_text: str


@router.patch("/api/{doc_id}")
async def api_save(
    doc_id: int,
    body: SaveRequest,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """編集テキスト保存"""
    result = await db.execute(
        select(LegalDocument).where(
            LegalDocument.id == doc_id,
            LegalDocument.user_id == user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "文書が見つかりません"}

    # 保存時も免責文言を先頭に保証
    text = service.ensure_disclaimer(body.edited_text)
    doc.edited_text = text
    await db.commit()
    return {"ok": True}


@router.post("/api/{doc_id}/regenerate")
async def api_regenerate(
    doc_id: int,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """再生成API"""
    result = await db.execute(
        select(LegalDocument).where(
            LegalDocument.id == doc_id,
            LegalDocument.user_id == user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "文書が見つかりません"}

    used = await get_monthly_usage(db, user.id, "legalgen")
    if err := limit_error("legalgen", used, get_limit("legalgen")):
        return {"error": err}

    try:
        params = json.loads(doc.input_params)
    except Exception:
        params = {}

    try:
        generated_text = await service.generate_legal_document(doc.doc_type, params)
    except Exception as e:
        return {"error": f"AI生成に失敗しました: {str(e)}"}

    doc.generated_text = generated_text
    doc.edited_text = None
    await db.commit()

    return {"generated_text": generated_text}


@router.delete("/api/{doc_id}")
async def api_delete(
    doc_id: int,
    user: User = Depends(require_tool_access("legalgen")),
    db: AsyncSession = Depends(get_db),
):
    """削除API"""
    result = await db.execute(
        select(LegalDocument).where(
            LegalDocument.id == doc_id,
            LegalDocument.user_id == user.id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "文書が見つかりません"}

    await db.delete(doc)
    await db.commit()
    return {"ok": True}
