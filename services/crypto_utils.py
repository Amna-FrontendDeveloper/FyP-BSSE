import os
from cryptography.fernet import Fernet


def _get_fernet():
    key = os.getenv("APP_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("APP_ENCRYPTION_KEY is missing from .env")
    return Fernet(key.encode())


def encrypt_value(plain_text):
    if not plain_text:
        return None
    return _get_fernet().encrypt(plain_text.encode()).decode()


def decrypt_value(encrypted_text):
    if not encrypted_text:
        return None
    return _get_fernet().decrypt(encrypted_text.encode()).decode()