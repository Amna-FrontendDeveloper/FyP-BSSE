"""Run with: python -m pytest tests/test_crypto_utils.py -q"""

import pytest
from cryptography.fernet import Fernet, InvalidToken

import database.database as db
from services.crypto_utils import decrypt_value, encrypt_value


def test_encrypt_and_decrypt_round_trip(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    secret = "ck_example_secret"

    encrypted = encrypt_value(secret)

    assert encrypted != secret
    assert decrypt_value(encrypted) == secret


@pytest.mark.parametrize("empty_value", [None, ""])
def test_empty_values_return_none(empty_value):
    assert encrypt_value(empty_value) is None
    assert decrypt_value(empty_value) is None


def test_encrypt_requires_an_encryption_key(monkeypatch):
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="APP_ENCRYPTION_KEY"):
        encrypt_value("secret")


def test_decrypt_rejects_invalid_ciphertext(monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())

    with pytest.raises(InvalidToken):
        decrypt_value("not-valid-ciphertext")


def test_woocommerce_credentials_are_encrypted_in_database(test_app, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    user_id = db.get_or_create_guest_user()
    consumer_key = "ck_example_key"
    consumer_secret = "cs_example_secret"

    db.save_woocommerce_integration(
        user_id,
        "https://store.example",
        encrypt_value(consumer_key),
        encrypt_value(consumer_secret),
    )
    integration = db.get_integration(user_id, "ecommerce")

    assert integration["api_key"] != consumer_key
    assert integration["api_secret"] != consumer_secret
    assert decrypt_value(integration["api_key"]) == consumer_key
    assert decrypt_value(integration["api_secret"]) == consumer_secret