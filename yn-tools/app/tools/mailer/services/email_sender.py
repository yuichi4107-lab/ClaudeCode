"""Email sending service via SMTP."""

import re
import smtplib
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from app.tools.mailer.models import MailerSmtpConfig
from app.tools.mailer.services.crypto import decrypt_password


def extract_placeholders(text: str) -> list[str]:
    """Return unique placeholder names found in text like {{name}}."""
    return list(dict.fromkeys(re.findall(r"\{\{(\w+)\}\}", text)))


def fill_placeholders(text: str, values: dict) -> str:
    """Replace {{key}} placeholders with values."""
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    return text


def send_email(
    smtp_config: MailerSmtpConfig,
    recipient_email: str,
    subject: str,
    body: str,
    attachment_paths: list[str] | None = None,
) -> tuple[bool, str]:
    """Send an email via SMTP. Returns (success, error_message)."""
    if not smtp_config or not smtp_config.host or not smtp_config.username:
        return False, "SMTP設定が未完了です。設定画面からSMTP情報を登録してください。"

    password = decrypt_password(smtp_config.password_encrypted)
    if not password:
        return False, "SMTPパスワードの復号に失敗しました。再設定してください。"

    msg = MIMEMultipart()
    if smtp_config.from_name:
        msg["From"] = formataddr(
            (str(Header(smtp_config.from_name, "utf-8")), smtp_config.from_email or smtp_config.username)
        )
    else:
        msg["From"] = smtp_config.from_email or smtp_config.username
    msg["To"] = recipient_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    for filepath in attachment_paths or []:
        p = Path(filepath)
        if not p.exists():
            continue
        part = MIMEBase("application", "octet-stream")
        with open(p, "rb") as bf:
            part.set_payload(bf.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", p.name),
        )
        msg.attach(part)

    try:
        from_addr = smtp_config.from_email or smtp_config.username
        if smtp_config.port == 465:
            server = smtplib.SMTP_SSL(smtp_config.host, smtp_config.port, timeout=30)
            server.login(smtp_config.username, password)
        else:
            server = smtplib.SMTP(smtp_config.host, smtp_config.port, timeout=30)
            server.ehlo()
            if smtp_config.use_tls:
                server.starttls()
            server.login(smtp_config.username, password)

        server.sendmail(from_addr, [recipient_email], msg.as_string())
        server.quit()
        return True, ""
    except Exception as e:
        return False, str(e)
