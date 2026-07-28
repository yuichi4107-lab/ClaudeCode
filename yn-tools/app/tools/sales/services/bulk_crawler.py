"""一括HP巡回サービス（user_id版）"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.tools.sales.models import SalesCompany, SalesContact, SalesCrmStatus
from app.tools.sales.services.hp_crawler import crawl_website


async def bulk_crawl(
    db: AsyncSession,
    user_id: int,
    company_ids: list[int] | None = None,
    only_uncrawled: bool = True,
) -> dict:
    """複数企業のHPを一括巡回する。"""
    query = (
        select(SalesCompany)
        .where(SalesCompany.user_id == user_id)
        .options(
            selectinload(SalesCompany.contacts),
            selectinload(SalesCompany.crm_status),
        )
    )
    if company_ids:
        query = query.where(SalesCompany.id.in_(company_ids))
    if only_uncrawled:
        query = query.where(
            SalesCompany.website_url.isnot(None), SalesCompany.website_url != ""
        )

    result = await db.execute(query)
    companies = list(result.scalars().all())

    if only_uncrawled:
        companies = [c for c in companies if not c.contacts]

    total = len(companies)
    crawled = 0
    skipped = 0
    results = []

    for company in companies:
        if not company.website_url:
            skipped += 1
            results.append({
                "id": company.id, "name": company.name,
                "status": "skipped", "reason": "URLなし",
            })
            continue

        try:
            cr = await crawl_website(company.website_url)

            if cr["pages_crawled"] == 0:
                skipped += 1
                results.append({
                    "id": company.id, "name": company.name,
                    "status": "skipped", "reason": "アクセス不可",
                })
                continue

            if cr["description"] and not company.description:
                company.description = cr["description"]

            # Save emails
            for email_info in cr["emails"]:
                existing = await db.execute(
                    select(SalesContact).where(
                        SalesContact.company_id == company.id,
                        SalesContact.email == email_info["email"],
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(SalesContact(
                        company_id=company.id,
                        email=email_info["email"],
                        email_type=email_info["type"],
                        sns_instagram=cr["sns"].get("instagram"),
                        sns_twitter=cr["sns"].get("twitter"),
                        sns_facebook=cr["sns"].get("facebook"),
                    ))

            # Save forms
            for form_url in cr["contact_form_urls"]:
                existing = await db.execute(
                    select(SalesContact).where(
                        SalesContact.company_id == company.id,
                        SalesContact.contact_form_url == form_url,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(SalesContact(
                        company_id=company.id,
                        contact_form_url=form_url,
                        sns_instagram=cr["sns"].get("instagram"),
                        sns_twitter=cr["sns"].get("twitter"),
                        sns_facebook=cr["sns"].get("facebook"),
                    ))

            # SNS-only contact
            if not cr["emails"] and not cr["contact_form_urls"]:
                sns = cr["sns"]
                if any(sns.values()):
                    db.add(SalesContact(
                        company_id=company.id,
                        sns_instagram=sns.get("instagram"),
                        sns_twitter=sns.get("twitter"),
                        sns_facebook=sns.get("facebook"),
                    ))

            # Update score
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

            await db.flush()
            crawled += 1
            results.append({
                "id": company.id, "name": company.name, "status": "crawled",
                "pages": cr["pages_crawled"],
                "emails": len(cr["emails"]),
                "forms": len(cr["contact_form_urls"]),
                "score": company.crm_status.score if company.crm_status else 0,
            })

        except Exception as e:
            skipped += 1
            results.append({
                "id": company.id, "name": company.name,
                "status": "error", "reason": str(e)[:100],
            })

    await db.commit()
    return {"total": total, "crawled": crawled, "skipped": skipped, "results": results}
