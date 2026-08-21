"""Sales automation routes - migrated from standalone app.

All org_id references replaced with user_id from portal auth.
URL prefix: /tools/sales/
"""

import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from app.core.templates import make_templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.tools.sales.models import (
    SalesCampaign, SalesCompany, SalesContact,
    SalesCrmStatus, SalesOutreachLog, SalesSmtpConfig,
)
from app.tools.sales.services.bulk_crawler import bulk_crawl
from app.tools.sales.services.company_search import search_and_save
from app.tools.sales.services.email_sender import send_bulk_campaign
from app.tools.sales.services.export import export_csv, export_excel
from app.tools.sales.services.hp_crawler import crawl_website
from app.users.models import User

router = APIRouter(prefix="/tools/sales", tags=["sales"])
templates = make_templates("app/templates")

P = "/tools/sales"  # URL prefix shorthand


# ===========================================================================
# Dashboard
# ===========================================================================
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    uid = user.id

    # Stats
    total = (await db.execute(
        select(func.count(SalesCompany.id)).where(SalesCompany.user_id == uid)
    )).scalar() or 0

    with_email = (await db.execute(
        select(func.count(func.distinct(SalesContact.company_id)))
        .join(SalesCompany, SalesContact.company_id == SalesCompany.id)
        .where(SalesCompany.user_id == uid, SalesContact.email.isnot(None))
    )).scalar() or 0

    with_form = (await db.execute(
        select(func.count(func.distinct(SalesContact.company_id)))
        .join(SalesCompany, SalesContact.company_id == SalesCompany.id)
        .where(SalesCompany.user_id == uid, SalesContact.contact_form_url.isnot(None))
    )).scalar() or 0

    avg_score = (await db.execute(
        select(func.avg(SalesCrmStatus.score))
        .join(SalesCompany, SalesCrmStatus.company_id == SalesCompany.id)
        .where(SalesCompany.user_id == uid)
    )).scalar() or 0

    with_url = (await db.execute(
        select(func.count(SalesCompany.id)).where(
            SalesCompany.user_id == uid,
            SalesCompany.website_url.isnot(None), SalesCompany.website_url != "",
        )
    )).scalar() or 0

    crawled_count = (await db.execute(
        select(func.count(func.distinct(SalesContact.company_id)))
        .join(SalesCompany, SalesContact.company_id == SalesCompany.id)
        .where(SalesCompany.user_id == uid)
    )).scalar() or 0

    # Status counts
    statuses = ["未営業", "送信済", "返信あり", "商談", "契約"]
    status_counts = {}
    for s in statuses:
        cnt = (await db.execute(
            select(func.count(SalesCrmStatus.id))
            .join(SalesCompany, SalesCrmStatus.company_id == SalesCompany.id)
            .where(SalesCompany.user_id == uid, SalesCrmStatus.status == s)
        )).scalar() or 0
        status_counts[s] = cnt

    blacklist_count = (await db.execute(
        select(func.count(SalesCrmStatus.id))
        .join(SalesCompany, SalesCrmStatus.company_id == SalesCompany.id)
        .where(SalesCompany.user_id == uid, SalesCrmStatus.is_blacklisted == True)
    )).scalar() or 0

    # Top 10 by score
    top_result = await db.execute(
        select(SalesCompany)
        .join(SalesCrmStatus)
        .options(selectinload(SalesCompany.crm_status))
        .where(SalesCompany.user_id == uid)
        .order_by(SalesCrmStatus.score.desc())
        .limit(10)
    )
    top_raw = top_result.scalars().all()
    top_companies = [
        {"id": c.id, "name": c.name, "industry": c.industry,
         "score": c.crm_status.score if c.crm_status else 0,
         "status": c.crm_status.status if c.crm_status else ""}
        for c in top_raw
    ]

    # Campaign stats
    total_campaigns = (await db.execute(
        select(func.count(SalesCampaign.id)).where(SalesCampaign.user_id == uid)
    )).scalar() or 0
    total_sent = (await db.execute(
        select(func.count(SalesOutreachLog.id)).where(
            SalesOutreachLog.user_id == uid, SalesOutreachLog.status == "sent",
        )
    )).scalar() or 0

    return templates.TemplateResponse(request, "tools/sales/dashboard.html", {
        "user": user, "page": "sales",
        "total_companies": total, "total_with_email": with_email,
        "total_with_form": with_form, "avg_score": round(avg_score),
        "with_url": with_url, "crawled_count": crawled_count,
        "statuses": statuses, "status_counts": status_counts,
        "blacklist_count": blacklist_count,
        "top_companies": top_companies,
        "total_campaigns": total_campaigns, "total_sent": total_sent,
        "P": P,
    })


# ===========================================================================
# Companies
# ===========================================================================
@router.get("/companies", response_class=HTMLResponse)
async def companies_list(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    search: str = Query(""),
):
    uid = user.id
    per_page = 50
    query = (
        select(SalesCompany)
        .options(selectinload(SalesCompany.contacts), selectinload(SalesCompany.crm_status))
        .where(SalesCompany.user_id == uid)
    )
    if search:
        like = f"%{search}%"
        query = query.where(
            SalesCompany.name.ilike(like)
            | SalesCompany.industry.ilike(like)
            | SalesCompany.region.ilike(like)
        )
    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0
    query = query.order_by(SalesCompany.id.desc()).offset((page - 1) * per_page).limit(per_page)
    companies = (await db.execute(query)).scalars().all()

    return templates.TemplateResponse(request, "tools/sales/companies/list.html", {
        "user": user, "page_num": page, "per_page": per_page,
        "search": search, "total": total, "companies": companies, "P": P,
    })


@router.get("/companies/search", response_class=HTMLResponse)
async def companies_search_page(request: Request, user: User = Depends(require_tool_access("sales"))):
    return templates.TemplateResponse(request, "tools/sales/companies/search.html", {
        "user": user, "P": P,
    })


@router.post("/companies/search", response_class=HTMLResponse)
async def companies_search_action(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    query: str = Form(...),
    region: str = Form(""),
    max_results: int = Form(20),
):
    saved = await search_and_save(db, query, region, max_results, user_id=user.id)
    return templates.TemplateResponse(request, "tools/sales/companies/search_results.html", {
        "user": user, "companies": saved,
        "query": query, "region": region, "P": P,
    })


@router.get("/companies/{company_id}", response_class=HTMLResponse)
async def company_detail(
    request: Request, company_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SalesCompany)
        .options(selectinload(SalesCompany.contacts), selectinload(SalesCompany.crm_status))
        .where(SalesCompany.id == company_id, SalesCompany.user_id == user.id)
    )
    company = result.scalar_one_or_none()
    if not company:
        return HTMLResponse("Not Found", status_code=404)
    return templates.TemplateResponse(request, "tools/sales/companies/detail.html", {
        "user": user, "company": company, "P": P,
    })


@router.post("/companies/{company_id}/crawl", response_class=HTMLResponse)
async def company_crawl(
    request: Request, company_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SalesCompany)
        .options(selectinload(SalesCompany.contacts), selectinload(SalesCompany.crm_status))
        .where(SalesCompany.id == company_id, SalesCompany.user_id == user.id)
    )
    company = result.scalar_one_or_none()
    if not company or not company.website_url:
        return RedirectResponse(url=f"{P}/companies", status_code=303)

    cr = await crawl_website(company.website_url)

    if cr["description"] and not company.description:
        company.description = cr["description"]

    for ei in cr["emails"]:
        existing = await db.execute(
            select(SalesContact).where(
                SalesContact.company_id == company.id, SalesContact.email == ei["email"]
            )
        )
        if not existing.scalar_one_or_none():
            db.add(SalesContact(
                company_id=company.id, email=ei["email"], email_type=ei["type"],
                sns_instagram=cr["sns"].get("instagram"),
                sns_twitter=cr["sns"].get("twitter"),
                sns_facebook=cr["sns"].get("facebook"),
            ))

    for fu in cr["contact_form_urls"]:
        existing = await db.execute(
            select(SalesContact).where(
                SalesContact.company_id == company.id, SalesContact.contact_form_url == fu
            )
        )
        if not existing.scalar_one_or_none():
            db.add(SalesContact(
                company_id=company.id, contact_form_url=fu,
                sns_instagram=cr["sns"].get("instagram"),
                sns_twitter=cr["sns"].get("twitter"),
                sns_facebook=cr["sns"].get("facebook"),
            ))

    if company.crm_status:
        score = 0
        if cr["emails"]:
            score += 30
        if company.website_url:
            score += 20
        if company.review_count and company.review_count >= 10:
            score += 20
        score += sum(1 for v in cr["sns"].values() if v) * 5
        if cr["contact_form_urls"]:
            score += 15
        company.crm_status.score = score

    await db.commit()
    return RedirectResponse(url=f"{P}/companies/{company_id}", status_code=303)


# ===========================================================================
# CRM
# ===========================================================================
@router.get("/crm", response_class=HTMLResponse)
async def crm_list(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    status: str = Query(""),
    sort: str = Query("score_desc"),
    search: str = Query(""),
    page: int = Query(1, ge=1),
):
    uid = user.id
    per_page = 50
    statuses = ["未営業", "送信済", "返信あり", "商談", "契約"]

    query = (
        select(SalesCompany)
        .join(SalesCrmStatus)
        .options(selectinload(SalesCompany.contacts), selectinload(SalesCompany.crm_status))
        .where(SalesCompany.user_id == uid, SalesCrmStatus.is_blacklisted == False)
    )
    if status:
        query = query.where(SalesCrmStatus.status == status)
    if search:
        like = f"%{search}%"
        query = query.where(
            SalesCompany.name.ilike(like)
            | SalesCompany.industry.ilike(like)
            | SalesCompany.region.ilike(like)
        )

    order = {
        "score_desc": SalesCrmStatus.score.desc(),
        "score_asc": SalesCrmStatus.score.asc(),
        "name": SalesCompany.name,
        "updated": SalesCrmStatus.updated_at.desc(),
    }.get(sort, SalesCrmStatus.score.desc())
    query = query.order_by(order)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0

    companies = (await db.execute(
        query.offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()

    status_counts = {}
    for s in statuses:
        cnt = (await db.execute(
            select(func.count(SalesCrmStatus.id))
            .join(SalesCompany)
            .where(SalesCompany.user_id == uid, SalesCrmStatus.status == s)
        )).scalar() or 0
        status_counts[s] = cnt

    blacklist_count = (await db.execute(
        select(func.count(SalesCrmStatus.id))
        .join(SalesCompany)
        .where(SalesCompany.user_id == uid, SalesCrmStatus.is_blacklisted == True)
    )).scalar() or 0

    return templates.TemplateResponse(request, "tools/sales/crm/list.html", {
        "user": user,
        "companies": companies, "statuses": statuses,
        "status_counts": status_counts, "blacklist_count": blacklist_count,
        "current_status": status, "current_sort": sort, "search": search,
        "page_num": page, "per_page": per_page, "total": total, "P": P,
    })


@router.post("/crm/{company_id}/status")
async def crm_update_status(
    request: Request, company_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    new_status: str = Form(...),
):
    result = await db.execute(
        select(SalesCrmStatus)
        .join(SalesCompany)
        .where(SalesCompany.id == company_id, SalesCompany.user_id == user.id)
    )
    crm = result.scalar_one_or_none()
    if crm:
        crm.status = new_status
        await db.commit()
    referer = request.headers.get("referer", f"{P}/crm")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/crm/{company_id}/memo")
async def crm_update_memo(
    company_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    memo: str = Form(""),
):
    result = await db.execute(
        select(SalesCrmStatus)
        .join(SalesCompany)
        .where(SalesCompany.id == company_id, SalesCompany.user_id == user.id)
    )
    crm = result.scalar_one_or_none()
    if crm:
        crm.memo = memo
        await db.commit()
    return RedirectResponse(url=f"{P}/companies/{company_id}", status_code=303)


@router.post("/crm/{company_id}/blacklist")
async def crm_toggle_blacklist(
    company_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SalesCrmStatus)
        .join(SalesCompany)
        .where(SalesCompany.id == company_id, SalesCompany.user_id == user.id)
    )
    crm = result.scalar_one_or_none()
    if crm:
        crm.is_blacklisted = not crm.is_blacklisted
        await db.commit()
    return RedirectResponse(url=f"{P}/companies/{company_id}", status_code=303)


# ===========================================================================
# Campaigns
# ===========================================================================
@router.get("/campaigns", response_class=HTMLResponse)
async def campaigns_list(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    uid = user.id
    campaigns = (await db.execute(
        select(SalesCampaign).where(SalesCampaign.user_id == uid).order_by(SalesCampaign.id.desc())
    )).scalars().all()

    campaign_stats = {}
    for c in campaigns:
        cnt = (await db.execute(
            select(func.count(SalesOutreachLog.id)).where(
                SalesOutreachLog.campaign_id == c.id, SalesOutreachLog.status == "sent",
            )
        )).scalar() or 0
        campaign_stats[c.id] = cnt

    unsent = (await db.execute(
        select(func.count(SalesCrmStatus.id))
        .join(SalesCompany)
        .where(SalesCompany.user_id == uid, SalesCrmStatus.status == "未営業")
    )).scalar() or 0

    return templates.TemplateResponse(request, "tools/sales/campaigns/list.html", {
        "user": user,
        "campaigns": campaigns, "campaign_stats": campaign_stats,
        "unsent_count": unsent, "P": P,
    })


@router.get("/campaigns/new", response_class=HTMLResponse)
async def campaign_new_page(request: Request, user: User = Depends(require_tool_access("sales"))):
    return templates.TemplateResponse(request, "tools/sales/campaigns/new.html", {
        "user": user, "P": P,
    })


@router.post("/campaigns/new")
async def campaign_create(
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    subject_template: str = Form(...),
    body_template: str = Form(...),
):
    c = SalesCampaign(
        user_id=user.id, name=name,
        subject_template=subject_template, body_template=body_template,
    )
    db.add(c)
    await db.commit()
    return RedirectResponse(url=f"{P}/campaigns/{c.id}", status_code=303)


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(
    request: Request, campaign_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    campaign = (await db.execute(
        select(SalesCampaign).where(
            SalesCampaign.id == campaign_id, SalesCampaign.user_id == user.id,
        )
    )).scalar_one_or_none()
    if not campaign:
        return HTMLResponse("Not Found", status_code=404)

    logs = (await db.execute(
        select(SalesOutreachLog).where(
            SalesOutreachLog.campaign_id == campaign_id,
        ).order_by(SalesOutreachLog.id.desc()).limit(100)
    )).scalars().all()

    sent_count = sum(1 for l in logs if l.status == "sent")
    failed_count = sum(1 for l in logs if l.status == "failed")

    return templates.TemplateResponse(request, "tools/sales/campaigns/detail.html", {
        "user": user,
        "campaign": campaign, "logs": logs,
        "sent_count": sent_count, "failed_count": failed_count, "P": P,
    })


@router.post("/campaigns/{campaign_id}/edit")
async def campaign_edit(
    campaign_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    status: str = Form("draft"),
    subject_template: str = Form(...),
    body_template: str = Form(...),
):
    campaign = (await db.execute(
        select(SalesCampaign).where(
            SalesCampaign.id == campaign_id, SalesCampaign.user_id == user.id,
        )
    )).scalar_one_or_none()
    if campaign:
        campaign.name = name
        campaign.status = status
        campaign.subject_template = subject_template
        campaign.body_template = body_template
        await db.commit()
    return RedirectResponse(url=f"{P}/campaigns/{campaign_id}", status_code=303)


@router.post("/campaigns/{campaign_id}/send", response_class=HTMLResponse)
async def campaign_send(
    request: Request, campaign_id: int,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    mode: str = Form("dry_run"),
):
    dry_run = mode != "send"
    result = await send_bulk_campaign(db, campaign_id, user_id=user.id, dry_run=dry_run)

    return templates.TemplateResponse(request, "tools/sales/campaigns/send_results.html", {
        "user": user,
        "result": result, "campaign_id": campaign_id, "P": P,
    })


# ===========================================================================
# Scraper
# ===========================================================================
@router.get("/scraper", response_class=HTMLResponse)
async def scraper_index(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
):
    uid = user.id
    total = (await db.execute(
        select(func.count(SalesCompany.id)).where(SalesCompany.user_id == uid)
    )).scalar() or 0

    with_url = (await db.execute(
        select(func.count(SalesCompany.id)).where(
            SalesCompany.user_id == uid,
            SalesCompany.website_url.isnot(None), SalesCompany.website_url != "",
        )
    )).scalar() or 0

    crawled = (await db.execute(
        select(func.count(func.distinct(SalesContact.company_id)))
        .join(SalesCompany)
        .where(SalesCompany.user_id == uid)
    )).scalar() or 0

    uncrawled = with_url - crawled if with_url > crawled else 0

    return templates.TemplateResponse(request, "tools/sales/scraper/index.html", {
        "user": user,
        "total": total, "with_url": with_url, "uncrawled": uncrawled, "P": P,
    })


@router.post("/scraper/bulk", response_class=HTMLResponse)
async def scraper_bulk(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    mode: str = Form("uncrawled"),
):
    only_uncrawled = mode == "uncrawled"
    result = await bulk_crawl(db, user_id=user.id, only_uncrawled=only_uncrawled)
    return templates.TemplateResponse(request, "tools/sales/scraper/results.html", {
        "user": user, "result": result, "P": P,
    })


# ===========================================================================
# Export
# ===========================================================================
@router.get("/export/csv")
async def export_csv_route(
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    status: str = Query(""),
):
    csv_data = await export_csv(db, user.id, status_filter=status)
    bom = "\ufeff"
    return Response(
        content=(bom + csv_data).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="companies_{datetime.now():%Y%m%d}.csv"'},
    )


@router.get("/export/excel")
async def export_excel_route(
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    status: str = Query(""),
):
    data = await export_excel(db, user.id, status_filter=status)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="companies_{datetime.now():%Y%m%d}.xlsx"'},
    )


# ===========================================================================
# Settings (SMTP)
# ===========================================================================
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    message: str = Query(""),
    error: str = Query(""),
):
    result = await db.execute(
        select(SalesSmtpConfig).where(SalesSmtpConfig.user_id == user.id)
    )
    cfg = result.scalar_one_or_none()
    smtp = {
        "smtp_host": cfg.smtp_host if cfg else "",
        "smtp_port": str(cfg.smtp_port) if cfg else "465",
        "smtp_user": cfg.smtp_user if cfg else "",
        "smtp_password": cfg.smtp_password if cfg else "",
        "smtp_from_name": cfg.smtp_from_name if cfg else "",
    }
    return templates.TemplateResponse(request, "tools/sales/settings/index.html", {
        "user": user,
        "smtp": smtp, "message": message, "error": error, "P": P,
    })


@router.post("/settings/smtp")
async def settings_smtp_save(
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    smtp_host: str = Form(""),
    smtp_port: str = Form("465"),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from_name: str = Form(""),
):
    result = await db.execute(
        select(SalesSmtpConfig).where(SalesSmtpConfig.user_id == user.id)
    )
    cfg = result.scalar_one_or_none()
    if cfg:
        cfg.smtp_host = smtp_host
        cfg.smtp_port = int(smtp_port) if smtp_port.isdigit() else 465
        cfg.smtp_user = smtp_user
        cfg.smtp_password = smtp_password
        cfg.smtp_from_name = smtp_from_name
    else:
        db.add(SalesSmtpConfig(
            user_id=user.id, smtp_host=smtp_host,
            smtp_port=int(smtp_port) if smtp_port.isdigit() else 465,
            smtp_user=smtp_user, smtp_password=smtp_password,
            smtp_from_name=smtp_from_name,
        ))
    await db.commit()
    return RedirectResponse(
        url=f"{P}/settings?message=SMTP設定を保存しました", status_code=303,
    )


@router.post("/settings/smtp/test")
async def settings_smtp_test(
    user: User = Depends(require_tool_access("sales")),
    db: AsyncSession = Depends(get_db),
    test_to: str = Form(...),
):
    from app.tools.sales.services.email_sender import _send_email_smtp, _get_smtp

    smtp = await _get_smtp(db, user.id)
    if not all([smtp.get("smtp_host"), smtp.get("smtp_user"), smtp.get("smtp_password")]):
        return RedirectResponse(
            url=f"{P}/settings?error=SMTP設定が未完了です", status_code=303,
        )

    from_name = smtp.get("smtp_from_name", "")
    from_email = smtp["smtp_user"]
    from_addr = f"{from_name} <{from_email}>" if from_name else from_email

    import asyncio
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(
        None, _send_email_smtp,
        test_to, "YN Tools テスト送信",
        "これはYN Tools営業自動化ツールからのテスト送信です。\n正常に受信できています。",
        from_addr, smtp["smtp_host"], int(smtp.get("smtp_port", 465)),
        smtp["smtp_user"], smtp["smtp_password"],
    )

    if success:
        return RedirectResponse(
            url=f"{P}/settings?message=テストメールを送信しました", status_code=303,
        )
    return RedirectResponse(
        url=f"{P}/settings?error=送信に失敗しました。設定を確認してください", status_code=303,
    )
