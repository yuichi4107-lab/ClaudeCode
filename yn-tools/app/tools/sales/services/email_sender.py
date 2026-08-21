"""営業メール送信サービス（user_id版）"""

import asyncio
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from string import Template

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.tools.sales.models import (
    SalesCampaign, SalesCompany, SalesContact,
    SalesCrmStatus, SalesOutreachLog, SalesSmtpConfig,
)


def _render_template(template_str: str, company: SalesCompany, contact: SalesContact) -> str:
    t = Template(template_str)
    return t.safe_substitute(
        company_name=company.name or "",
        address=company.address or "",
        industry=company.industry or "",
        region=company.region or "",
        email=contact.email or "",
    )


def _send_email_smtp(
    to_email: str, subject: str, body: str, from_email: str,
    smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
) -> bool:
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        return True
    except Exception:
        return False


async def _get_smtp(db: AsyncSession, user_id: int) -> dict:
    result = await db.execute(
        select(SalesSmtpConfig).where(SalesSmtpConfig.user_id == user_id)
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        return {}
    return {
        "smtp_host": cfg.smtp_host,
        "smtp_port": cfg.smtp_port,
        "smtp_user": cfg.smtp_user,
        "smtp_password": cfg.smtp_password,
        "smtp_from_name": cfg.smtp_from_name,
    }


async def send_campaign_email(
    db: AsyncSession, campaign_id: int, company_id: int,
    contact_id: int, user_id: int, dry_run: bool = False,
) -> dict:
    campaign = await db.get(SalesCampaign, campaign_id)
    company = await db.get(SalesCompany, company_id)
    contact = await db.get(SalesContact, contact_id)

    if not campaign or not company or not contact or not contact.email:
        return {"status": "error", "reason": "データが見つかりません"}
    if company.user_id != user_id or campaign.user_id != user_id:
        return {"status": "error", "reason": "権限がありません"}

    subject = _render_template(campaign.subject_template or "", company, contact)
    body = _render_template(campaign.body_template or "", company, contact)

    if dry_run:
        return {"status": "preview", "to": contact.email, "subject": subject, "body": body}

    smtp = await _get_smtp(db, user_id)
    if not all([smtp.get("smtp_host"), smtp.get("smtp_user"), smtp.get("smtp_password")]):
        return {"status": "error", "reason": "SMTP設定が未完了です。設定画面から設定してください。"}

    from_name = smtp.get("smtp_from_name", "")
    from_email = smtp["smtp_user"]
    from_addr = f"{from_name} <{from_email}>" if from_name else from_email

    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(
        None, _send_email_smtp,
        contact.email, subject, body, from_addr,
        smtp["smtp_host"], int(smtp.get("smtp_port", 465)),
        smtp["smtp_user"], smtp["smtp_password"],
    )

    log = SalesOutreachLog(
        user_id=user_id, company_id=company_id, contact_id=contact_id,
        campaign_id=campaign_id, type="email",
        status="sent" if success else "failed",
        sent_at=datetime.now() if success else None,
    )
    db.add(log)

    if success:
        crm = await db.execute(
            select(SalesCrmStatus).where(SalesCrmStatus.company_id == company_id)
        )
        crm_status = crm.scalar_one_or_none()
        if crm_status and crm_status.status == "未営業":
            crm_status.status = "送信済"

    await db.commit()
    return {"status": "sent" if success else "failed", "to": contact.email, "subject": subject}


async def send_bulk_campaign(
    db: AsyncSession, campaign_id: int, user_id: int,
    company_ids: list[int] | None = None,
    dry_run: bool = False, delay_sec: float = 5.0,
) -> dict:
    campaign = await db.get(SalesCampaign, campaign_id)
    if not campaign:
        return {"status": "error", "reason": "メール送信設定が見つかりません"}

    query = (
        select(SalesCompany)
        .join(SalesCrmStatus)
        .options(selectinload(SalesCompany.contacts), selectinload(SalesCompany.crm_status))
        .where(
            SalesCompany.user_id == user_id,
            SalesCrmStatus.status == "未営業",
            SalesCrmStatus.is_blacklisted == False,
        )
    )
    if company_ids:
        query = query.where(SalesCompany.id.in_(company_ids))

    result = await db.execute(query)
    companies = list(result.scalars().all())

    results = []
    sent_count = failed_count = skipped_count = 0

    for company in companies:
        email_contacts = [c for c in company.contacts if c.email]
        if not email_contacts:
            skipped_count += 1
            results.append({"company": company.name, "status": "skipped", "reason": "メールアドレスなし"})
            continue

        existing = await db.execute(
            select(SalesOutreachLog).where(
                SalesOutreachLog.company_id == company.id,
                SalesOutreachLog.campaign_id == campaign_id,
                SalesOutreachLog.status == "sent",
            )
        )
        if existing.scalar_one_or_none():
            skipped_count += 1
            results.append({"company": company.name, "status": "skipped", "reason": "送信済み"})
            continue

        contact = email_contacts[0]
        sr = await send_campaign_email(
            db, campaign_id, company.id, contact.id, user_id=user_id, dry_run=dry_run,
        )

        if sr["status"] in ("sent", "preview"):
            sent_count += 1
        else:
            failed_count += 1

        results.append({
            "company": company.name, "to": sr.get("to", ""),
            "subject": sr.get("subject", ""), "status": sr["status"],
            "reason": sr.get("reason", ""), "body": sr.get("body", ""),
        })

        if not dry_run and sr["status"] == "sent":
            await asyncio.sleep(delay_sec)

    return {
        "campaign": campaign.name, "total": len(companies),
        "sent": sent_count, "failed": failed_count, "skipped": skipped_count,
        "dry_run": dry_run, "results": results,
    }
