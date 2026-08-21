"""SMTP password encryption/decryption using Fernet."""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _get_fernet():
    key = getattr(settings, "encryption_key", "")
    if not key:
        raise ValueError("ENCRYPTION_KEY is not set.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_password(plain: str) -> str:
    if not plain:
        return ""
    f = _get_fernet()
    return f.encrypt(plain.encode()).decode()


def decrypt_password(encrypted: str) -> str:
    if not encrypted:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        return ""
