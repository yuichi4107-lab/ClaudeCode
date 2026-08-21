"""ステップメール作成ツール - ルーター"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from app.core.templates import make_templates
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import StepMailItem, StepMailSeries
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/stepmail", tags=["stepmail"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def stepmail_index(
    request: Request,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """ステップメール ダッシュボード"""
    result = await db.execute(
        select(StepMailSeries)
        .where(StepMailSeries.user_id == user.id)
        .order_by(StepMailSeries.created_at.desc())
        .limit(50)
    )
    series_list = result.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "stepmail")

    return templates.TemplateResponse(
        request, "tools/stepmail/index.html", {
            "user": user,
            "page": "stepmail",
            "view": "dashboard",
            "series_list": series_list,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("stepmail"),
            "purpose_templates": service.BUSINESS_PURPOSE_TEMPLATES,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def stepmail_new(
    request: Request,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """新規シリーズ作成フォーム"""
    monthly_used = await get_monthly_usage(db, user.id, "stepmail")

    return templates.TemplateResponse(
        request, "tools/stepmail/index.html", {
            "user": user,
            "page": "stepmail",
            "view": "new",
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("stepmail"),
            "purpose_templates": service.BUSINESS_PURPOSE_TEMPLATES,
        }
    )


@router.get("/{series_id}", response_class=HTMLResponse)
async def stepmail_detail(
    series_id: int,
    request: Request,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """シリーズ詳細（全通アコーディオン表示）"""
    result = await db.execute(
        select(StepMailSeries).where(
            StepMailSeries.id == series_id,
            StepMailSeries.user_id == user.id,
        )
    )
    series = result.scalar_one_or_none()
    if not series:
        return RedirectResponse(url="/tools/stepmail/", status_code=303)

    items_result = await db.execute(
        select(StepMailItem)
        .where(StepMailItem.series_id == series_id)
        .order_by(StepMailItem.step_number)
    )
    items = items_result.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "stepmail")

    return templates.TemplateResponse(
        request, "tools/stepmail/index.html", {
            "user": user,
            "page": "stepmail",
            "view": "detail",
            "series": series,
            "items": items,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("stepmail"),
            "purpose_templates": service.BUSINESS_PURPOSE_TEMPLATES,
        }
    )


@router.post("/api/generate")
async def api_generate(
    request: Request,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
    business_purpose: str = Form(...),
    product_name: str = Form(...),
    target_audience: str = Form(...),
    step_count: int = Form(...),
    tone: str = Form(...),
    cta_url: str = Form(default=""),
    seller_name: str = Form(default=""),
    extra_info: str = Form(default=""),
):
    """シリーズ一括生成API"""
    used = await get_monthly_usage(db, user.id, "stepmail")
    if err := limit_error("stepmail", used, get_limit("stepmail")):
        return {"error": err}

    # 通数バリデーション
    if not (3 <= step_count <= 10):
        return {"error": "通数は3〜10の範囲で指定してください。"}

    try:
        emails = await service.generate_series(
            business_purpose=business_purpose,
            product_name=product_name,
            target_audience=target_audience,
            step_count=step_count,
            tone=tone,
            cta_url=cta_url or None,
            seller_name=seller_name or None,
            extra_info=extra_info or None,
        )
    except Exception as e:
        return {"error": f"AI生成に失敗しました: {str(e)}"}

    if not emails:
        return {"error": "メールが生成されませんでした。もう一度お試しください。"}

    # シリーズ保存
    month_str = datetime.now().strftime("%Y-%m")
    title = f"{product_name}_{month_str}"

    series = StepMailSeries(
        user_id=user.id,
        title=title,
        business_purpose=business_purpose,
        product_name=product_name,
        target_audience=target_audience,
        step_count=step_count,
        tone=tone,
        cta_url=cta_url or None,
        seller_name=seller_name or None,
        extra_info=extra_info or None,
        status="generated",
    )
    db.add(series)
    await db.flush()  # series.id を取得

    # 各通を保存
    items = []
    for email in emails:
        item = StepMailItem(
            series_id=series.id,
            user_id=user.id,
            step_number=email.get("step", 1),
            subject=email.get("subject", ""),
            preheader=email.get("preheader") or None,
            body=email.get("body", ""),
            cta_text=email.get("cta_text") or None,
        )
        db.add(item)
        items.append(item)

    await db.commit()
    await db.refresh(series)

    return {
        "series_id": series.id,
        "items": [
            {
                "id": item.id,
                "step_number": item.step_number,
                "subject": item.subject,
                "preheader": item.preheader,
                "body": item.body,
                "cta_text": item.cta_text,
            }
            for item in items
        ],
    }


class ItemUpdateRequest(BaseModel):
    subject: str
    preheader: str | None = None
    body: str
    cta_text: str | None = None


@router.patch("/api/item/{item_id}")
async def api_item_update(
    item_id: int,
    body: ItemUpdateRequest,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """個別通の保存（AUTO-SAVE）"""
    result = await db.execute(
        select(StepMailItem).where(
            StepMailItem.id == item_id,
            StepMailItem.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "メールが見つかりません"}

    item.subject = body.subject
    item.preheader = body.preheader or None
    item.body = body.body
    item.cta_text = body.cta_text or None
    await db.commit()
    return {"ok": True}


class RegenerateItemRequest(BaseModel):
    context_prev: str | None = None
    context_next: str | None = None


@router.post("/api/item/{item_id}/regenerate")
async def api_item_regenerate(
    item_id: int,
    body: RegenerateItemRequest,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """1通だけ再生成"""
    result = await db.execute(
        select(StepMailItem).where(
            StepMailItem.id == item_id,
            StepMailItem.user_id == user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return {"error": "メールが見つかりません"}

    # シリーズ情報を取得
    series_result = await db.execute(
        select(StepMailSeries).where(
            StepMailSeries.id == item.series_id,
            StepMailSeries.user_id == user.id,
        )
    )
    series = series_result.scalar_one_or_none()
    if not series:
        return {"error": "シリーズが見つかりません"}

    used = await get_monthly_usage(db, user.id, "stepmail")
    if err := limit_error("stepmail", used, get_limit("stepmail")):
        return {"error": err}

    try:
        new_data = await service.regenerate_single_item(
            business_purpose=series.business_purpose,
            product_name=series.product_name,
            target_audience=series.target_audience,
            tone=series.tone,
            step_number=item.step_number,
            total_steps=series.step_count,
            context_prev=body.context_prev,
            context_next=body.context_next,
            cta_url=series.cta_url,
            seller_name=series.seller_name,
        )
    except Exception as e:
        return {"error": f"再生成に失敗しました: {str(e)}"}

    if not new_data:
        return {"error": "再生成に失敗しました。もう一度お試しください。"}

    # DB更新
    item.subject = new_data.get("subject", item.subject)
    item.preheader = new_data.get("preheader") or item.preheader
    item.body = new_data.get("body", item.body)
    item.cta_text = new_data.get("cta_text") or item.cta_text
    await db.commit()

    return {
        "subject": item.subject,
        "preheader": item.preheader,
        "body": item.body,
        "cta_text": item.cta_text,
    }


@router.delete("/api/series/{series_id}")
async def api_series_delete(
    series_id: int,
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """シリーズ削除"""
    result = await db.execute(
        select(StepMailSeries).where(
            StepMailSeries.id == series_id,
            StepMailSeries.user_id == user.id,
        )
    )
    series = result.scalar_one_or_none()
    if not series:
        return {"error": "シリーズが見つかりません"}

    # 関連するアイテムも削除
    items_result = await db.execute(
        select(StepMailItem).where(StepMailItem.series_id == series_id)
    )
    for item in items_result.scalars().all():
        await db.delete(item)

    await db.delete(series)
    await db.commit()
    return {"ok": True}


@router.get("/api/series/{series_id}/export")
async def api_series_export(
    series_id: int,
    format: str = "text",
    user: User = Depends(require_tool_access("stepmail")),
    db: AsyncSession = Depends(get_db),
):
    """全通一括テキスト出力"""
    result = await db.execute(
        select(StepMailSeries).where(
            StepMailSeries.id == series_id,
            StepMailSeries.user_id == user.id,
        )
    )
    series = result.scalar_one_or_none()
    if not series:
        return {"error": "シリーズが見つかりません"}

    items_result = await db.execute(
        select(StepMailItem)
        .where(StepMailItem.series_id == series_id)
        .order_by(StepMailItem.step_number)
    )
    items = items_result.scalars().all()

    if format == "json":
        return {
            "series_title": series.title,
            "emails": [
                {
                    "step": item.step_number,
                    "subject": item.subject,
                    "preheader": item.preheader,
                    "body": item.body,
                    "cta_text": item.cta_text,
                }
                for item in items
            ],
        }

    # プレーンテキスト形式
    lines = []
    for item in items:
        lines.append(f"=== 第{item.step_number}通 ===")
        lines.append(f"件名: {item.subject}")
        if item.preheader:
            lines.append(f"プレヘッダー: {item.preheader}")
        lines.append("")
        lines.append(item.body)
        if item.cta_text:
            lines.append("")
            lines.append(f"【CTA】{item.cta_text}")
        lines.append("")

    return PlainTextResponse("\n".join(lines))
