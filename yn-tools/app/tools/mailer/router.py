"""Mailer tool routes - migrated from Flask mail-system to FastAPI."""

import csv
import io
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.tools.mailer.models import (
    MailerContact,
    MailerSendHistory,
    MailerSmtpConfig,
    MailerTemplate,
)
from app.tools.mailer.services.crypto import encrypt_password
from app.tools.mailer.services.email_sender import (
    extract_placeholders,
    fill_placeholders,
    send_email,
)
from app.users.models import User

router = APIRouter(prefix="/tools/mailer", tags=["mailer"])
templates = make_templates("app/templates")

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Dashboard / Send page
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    tpls = (await db.execute(
        select(MailerTemplate).where(MailerTemplate.user_id == user.id).order_by(MailerTemplate.name)
    )).scalars().all()
    contacts = (await db.execute(
        select(MailerContact).where(MailerContact.user_id == user.id).order_by(MailerContact.name)
    )).scalars().all()
    return templates.TemplateResponse(request, "tools/mailer/index.html", {
        "user": user, "templates": tpls, "contacts": contacts, "page": "send",
    })


@router.get("/api/template/{template_id}")
async def api_template(
    template_id: int,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == template_id, MailerTemplate.user_id == user.id)
    )
    t = result.scalar_one_or_none()
    if not t:
        return JSONResponse({"error": "not found"}, status_code=404)
    placeholders = extract_placeholders(t.subject + t.body)
    return JSONResponse({"id": t.id, "name": t.name, "subject": t.subject, "body": t.body, "placeholders": placeholders})


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
):
    form = await request.form()
    template_id = form.get("template_id", "")
    recipient_email = form.get("recipient_email", "")
    recipient_name = form.get("recipient_name", "")
    subject = form.get("subject", "")
    body = form.get("body", "")

    # Save uploaded files
    saved_uploads = []
    for key in form:
        if key == "extra_attachments":
            upload: UploadFile = form[key]
            if upload and hasattr(upload, "filename") and upload.filename:
                safe_name = f"{uuid.uuid4().hex[:8]}_{upload.filename}"
                save_path = UPLOAD_DIR / safe_name
                content = await upload.read()
                save_path.write_bytes(content)
                saved_uploads.append(str(save_path))

    request.session["pending_send"] = {
        "template_id": template_id,
        "recipient_email": recipient_email,
        "recipient_name": recipient_name,
        "subject": subject,
        "body": body,
        "attachments": saved_uploads,
    }

    attachment_names = [Path(a).name for a in saved_uploads]
    return templates.TemplateResponse(request, "tools/mailer/preview.html", {
        "user": user,
        "subject": subject, "body": body,
        "recipient_email": recipient_email, "recipient_name": recipient_name,
        "attachment_names": attachment_names, "page": "send",
    })


@router.post("/send")
async def send(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    pending = request.session.pop("pending_send", None)
    if not pending:
        return RedirectResponse(url="/tools/mailer/?msg=no_data", status_code=303)

    recipient_email = pending["recipient_email"]
    if not recipient_email:
        return RedirectResponse(url="/tools/mailer/?msg=no_email", status_code=303)

    smtp_result = await db.execute(
        select(MailerSmtpConfig).where(MailerSmtpConfig.user_id == user.id)
    )
    smtp_config = smtp_result.scalar_one_or_none()

    success, error = send_email(smtp_config, recipient_email, pending["subject"], pending["body"], pending.get("attachments"))

    attachment_names = ";".join(Path(a).name for a in pending.get("attachments", []))
    template_id = int(pending["template_id"]) if pending.get("template_id") else None

    history = MailerSendHistory(
        user_id=user.id,
        recipient_email=recipient_email,
        recipient_name=pending.get("recipient_name", ""),
        template_id=template_id,
        subject=pending["subject"],
        attachments=attachment_names,
        status="success" if success else f"error: {error}",
    )
    db.add(history)
    await db.commit()
    _cleanup_uploads(pending.get("attachments", []))

    msg = "sent" if success else "error"
    return RedirectResponse(url=f"/tools/mailer/?msg={msg}", status_code=303)


# ---------------------------------------------------------------------------
# Bulk send
# ---------------------------------------------------------------------------
@router.get("/bulk", response_class=HTMLResponse)
async def bulk(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    tpls = (await db.execute(
        select(MailerTemplate).where(MailerTemplate.user_id == user.id).order_by(MailerTemplate.name)
    )).scalars().all()
    contacts = (await db.execute(
        select(MailerContact).where(MailerContact.user_id == user.id).order_by(MailerContact.name)
    )).scalars().all()
    return templates.TemplateResponse(request, "tools/mailer/bulk.html", {
        "user": user, "templates": tpls, "contacts": contacts, "page": "bulk",
    })


@router.post("/bulk/preview", response_class=HTMLResponse)
async def bulk_preview(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    template_id = form.get("template_id", "")
    contact_ids = form.getlist("contact_ids")
    delay = float(form.get("delay", "3"))

    if not template_id or not contact_ids:
        return RedirectResponse(url="/tools/mailer/bulk?msg=missing", status_code=303)

    tpl_result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == int(template_id), MailerTemplate.user_id == user.id)
    )
    template = tpl_result.scalar_one_or_none()
    if not template:
        return RedirectResponse(url="/tools/mailer/bulk?msg=not_found", status_code=303)

    contacts_result = await db.execute(
        select(MailerContact).where(
            MailerContact.id.in_([int(c) for c in contact_ids]),
            MailerContact.user_id == user.id,
        )
    )
    contacts = contacts_result.scalars().all()

    preview_items = []
    for c in contacts:
        values = {"name": c.name, "company": c.company}
        subj = fill_placeholders(template.subject, values)
        bod = fill_placeholders(template.body, values)
        preview_items.append({
            "contact_id": c.id, "name": c.name, "email": c.email,
            "company": c.company, "subject": subj,
            "body_preview": bod[:100] + "..." if len(bod) > 100 else bod,
        })

    request.session["pending_bulk"] = {
        "template_id": template.id,
        "contact_ids": [c.id for c in contacts],
        "attachments": [],
        "delay": delay,
    }

    return templates.TemplateResponse(request, "tools/mailer/bulk_preview.html", {
        "user": user,
        "template": template, "preview_items": preview_items,
        "attachment_names": [], "delay": delay, "page": "bulk",
    })


@router.post("/bulk/send", response_class=HTMLResponse)
async def bulk_send(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    pending = request.session.pop("pending_bulk", None)
    if not pending:
        return RedirectResponse(url="/tools/mailer/bulk?msg=no_data", status_code=303)

    tpl_result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == pending["template_id"], MailerTemplate.user_id == user.id)
    )
    template = tpl_result.scalar_one_or_none()

    contacts_result = await db.execute(
        select(MailerContact).where(
            MailerContact.id.in_(pending["contact_ids"]),
            MailerContact.user_id == user.id,
        )
    )
    contacts = contacts_result.scalars().all()

    smtp_result = await db.execute(
        select(MailerSmtpConfig).where(MailerSmtpConfig.user_id == user.id)
    )
    smtp_config = smtp_result.scalar_one_or_none()
    delay = pending.get("delay", 3)

    results = []
    for i, c in enumerate(contacts):
        values = {"name": c.name, "company": c.company}
        subj = fill_placeholders(template.subject, values)
        bod = fill_placeholders(template.body, values)

        success, error = send_email(smtp_config, c.email, subj, bod, pending.get("attachments"))

        history = MailerSendHistory(
            user_id=user.id,
            recipient_email=c.email,
            recipient_name=c.name,
            template_id=template.id,
            subject=subj,
            attachments="",
            status="success" if success else f"error: {error}",
        )
        db.add(history)

        results.append({
            "name": c.name, "email": c.email, "company": c.company,
            "subject": subj, "status": "success" if success else "error", "error": error,
        })

        if success and i < len(contacts) - 1:
            time.sleep(delay)

    await db.commit()

    sent = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "error")

    return templates.TemplateResponse(request, "tools/mailer/bulk_results.html", {
        "user": user,
        "results": results, "sent": sent, "failed": failed, "total": len(results), "page": "bulk",
    })


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------
@router.get("/contacts", response_class=HTMLResponse)
async def contacts_list(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerContact).where(MailerContact.user_id == user.id).order_by(MailerContact.name)
    )
    contacts = result.scalars().all()
    return templates.TemplateResponse(request, "tools/mailer/contacts.html", {
        "user": user, "contacts": contacts, "page": "contacts",
    })


@router.post("/contacts/add")
async def contacts_add(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
    email: str = Form(...),
    name: str = Form(""),
    company: str = Form(""),
    notes: str = Form(""),
):
    contact = MailerContact(user_id=user.id, name=name.strip(), email=email.strip(), company=company.strip(), notes=notes.strip())
    db.add(contact)
    await db.commit()
    return RedirectResponse(url="/tools/mailer/contacts?msg=added", status_code=303)


@router.post("/contacts/edit/{contact_id}")
async def contacts_edit(
    contact_id: int,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
    email: str = Form(...),
    name: str = Form(""),
    company: str = Form(""),
    notes: str = Form(""),
):
    result = await db.execute(
        select(MailerContact).where(MailerContact.id == contact_id, MailerContact.user_id == user.id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        return RedirectResponse(url="/tools/mailer/contacts?msg=not_found", status_code=303)
    contact.name = name.strip()
    contact.email = email.strip()
    contact.company = company.strip()
    contact.notes = notes.strip()
    await db.commit()
    return RedirectResponse(url="/tools/mailer/contacts?msg=updated", status_code=303)


@router.post("/contacts/delete/{contact_id}")
async def contacts_delete(
    contact_id: int,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerContact).where(MailerContact.id == contact_id, MailerContact.user_id == user.id)
    )
    contact = result.scalar_one_or_none()
    if contact:
        await db.delete(contact)
        await db.commit()
    return RedirectResponse(url="/tools/mailer/contacts?msg=deleted", status_code=303)


@router.post("/contacts/import")
async def contacts_import(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    csv_file = form.get("csv_file")
    if not csv_file or not hasattr(csv_file, "read"):
        return RedirectResponse(url="/tools/mailer/contacts?msg=no_file", status_code=303)

    content = (await csv_file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    count = 0
    for row in reader:
        email_val = (row.get("email") or row.get("メールアドレス") or "").strip()
        if not email_val:
            continue
        contact = MailerContact(
            user_id=user.id,
            name=(row.get("name") or row.get("氏名") or "").strip(),
            email=email_val,
            company=(row.get("company") or row.get("会社名") or "").strip(),
            notes=(row.get("notes") or row.get("メモ") or "").strip(),
        )
        db.add(contact)
        count += 1
    await db.commit()
    return RedirectResponse(url=f"/tools/mailer/contacts?msg=imported&count={count}", status_code=303)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
@router.get("/templates", response_class=HTMLResponse)
async def templates_list(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.user_id == user.id).order_by(MailerTemplate.updated_at.desc())
    )
    tpls = result.scalars().all()
    return templates.TemplateResponse(request, "tools/mailer/templates_list.html", {
        "user": user, "mail_templates": tpls, "page": "templates",
    })


@router.get("/templates/new", response_class=HTMLResponse)
async def templates_new(request: Request, user: User = Depends(require_tool_access("mailer"))):
    return templates.TemplateResponse(request, "tools/mailer/templates_form.html", {
        "user": user, "mode": "new", "page": "templates",
    })


@router.post("/templates/new")
async def templates_create(
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
):
    tpl = MailerTemplate(user_id=user.id, name=name.strip(), subject=subject.strip(), body=body.strip())
    db.add(tpl)
    await db.commit()
    return RedirectResponse(url="/tools/mailer/templates?msg=created", status_code=303)


@router.get("/templates/edit/{template_id}", response_class=HTMLResponse)
async def templates_edit_page(
    template_id: int,
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == template_id, MailerTemplate.user_id == user.id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        return RedirectResponse(url="/tools/mailer/templates?msg=not_found", status_code=303)
    placeholders = extract_placeholders(tpl.subject + tpl.body)
    return templates.TemplateResponse(request, "tools/mailer/templates_form.html", {
        "user": user, "mode": "edit", "template": tpl, "placeholders": placeholders, "page": "templates",
    })


@router.post("/templates/edit/{template_id}")
async def templates_update(
    template_id: int,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
):
    result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == template_id, MailerTemplate.user_id == user.id)
    )
    tpl = result.scalar_one_or_none()
    if not tpl:
        return RedirectResponse(url="/tools/mailer/templates?msg=not_found", status_code=303)
    tpl.name = name.strip()
    tpl.subject = subject.strip()
    tpl.body = body.strip()
    await db.commit()
    return RedirectResponse(url="/tools/mailer/templates?msg=updated", status_code=303)


@router.post("/templates/delete/{template_id}")
async def templates_delete(
    template_id: int,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == template_id, MailerTemplate.user_id == user.id)
    )
    tpl = result.scalar_one_or_none()
    if tpl:
        await db.delete(tpl)
        await db.commit()
    return RedirectResponse(url="/tools/mailer/templates?msg=deleted", status_code=303)


@router.post("/templates/duplicate/{template_id}")
async def templates_duplicate(
    template_id: int,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerTemplate).where(MailerTemplate.id == template_id, MailerTemplate.user_id == user.id)
    )
    original = result.scalar_one_or_none()
    if not original:
        return RedirectResponse(url="/tools/mailer/templates?msg=not_found", status_code=303)
    copy = MailerTemplate(
        user_id=user.id, name=f"{original.name}（コピー）",
        subject=original.subject, body=original.body,
    )
    db.add(copy)
    await db.commit()
    await db.refresh(copy)
    return RedirectResponse(url=f"/tools/mailer/templates/edit/{copy.id}", status_code=303)


# ---------------------------------------------------------------------------
# SMTP Settings
# ---------------------------------------------------------------------------
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerSmtpConfig).where(MailerSmtpConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    has_password = bool(config and config.password_encrypted)
    return templates.TemplateResponse(request, "tools/mailer/settings.html", {
        "user": user, "config": config, "has_password": has_password, "page": "settings",
    })


@router.post("/settings")
async def settings_save(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    result = await db.execute(
        select(MailerSmtpConfig).where(MailerSmtpConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if not config:
        config = MailerSmtpConfig(user_id=user.id)
        db.add(config)

    config.host = form.get("host", "").strip()
    config.port = int(form.get("port", "587"))
    config.username = form.get("username", "").strip()
    config.from_name = form.get("from_name", "").strip()
    config.from_email = form.get("from_email", "").strip() or config.username
    config.use_tls = form.get("use_tls") == "on"

    password = form.get("password", "").strip()
    if password:
        config.password_encrypted = encrypt_password(password)

    await db.commit()
    return RedirectResponse(url="/tools/mailer/settings?msg=saved", status_code=303)


@router.post("/settings/test")
async def settings_test(
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerSmtpConfig).where(MailerSmtpConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config or not config.host:
        return RedirectResponse(url="/tools/mailer/settings?msg=no_config", status_code=303)

    success, error = send_email(
        config, user.email,
        "【テスト】SMTP設定の確認",
        f"このメールはYN Toolsメール送信ツールのSMTPテストです。\n\n送信元: {config.from_email or config.username}\nSMTPホスト: {config.host}:{config.port}\n\n設定が正しく動作しています。",
    )

    msg = "test_ok" if success else "test_error"
    return RedirectResponse(url=f"/tools/mailer/settings?msg={msg}", status_code=303)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@router.get("/history", response_class=HTMLResponse)
async def history_list(
    request: Request,
    user: User = Depends(require_tool_access("mailer")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MailerSendHistory)
        .where(MailerSendHistory.user_id == user.id)
        .order_by(MailerSendHistory.sent_at.desc())
        .limit(500)
    )
    records = result.scalars().all()
    return templates.TemplateResponse(request, "tools/mailer/history.html", {
        "user": user, "history": records, "page": "history",
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cleanup_uploads(paths):
    for att in paths or []:
        p = Path(att)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
