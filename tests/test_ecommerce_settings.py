import os

from cryptography.fernet import Fernet

import database.database as db
from conftest import login
from services.crypto_utils import decrypt_value


def test_ecommerce_settings_save_store_type_url_and_encrypted_api_key(
    client, user_id, monkeypatch
):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    login(client, user_id)

    response = client.post(
        "/integrations/ecommerce",
        data={
            "store_platform": "shopify",
            "store_url": "https://example.myshopify.com",
            "api_key": "shopify-secret-key",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    integration = db.get_integration(user_id, "ecommerce")
    assert integration["store_platform"] == "shopify"
    assert integration["store_url"] == "https://example.myshopify.com"
    assert integration["api_key"] != "shopify-secret-key"
    assert decrypt_value(integration["api_key"]) == "shopify-secret-key"


def test_ecommerce_settings_update_keeps_saved_api_key_when_blank(
    client, user_id, monkeypatch
):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    login(client, user_id)

    client.post(
        "/integrations/ecommerce",
        data={
            "store_platform": "woocommerce",
            "store_url": "https://shop.example.com",
            "api_key": "original-secret",
        },
    )
    original = db.get_integration(user_id, "ecommerce")["api_key"]

    response = client.post(
        "/integrations/ecommerce",
        data={
            "store_platform": "other",
            "store_url": "https://new.example.com",
            "api_key": "",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    updated = db.get_integration(user_id, "ecommerce")
    assert updated["store_platform"] == "other"
    assert updated["store_url"] == "https://new.example.com"
    assert updated["api_key"] == original


def test_ecommerce_settings_reject_invalid_store_type(client, user_id):
    login(client, user_id)

    response = client.post(
        "/integrations/ecommerce",
        data={
            "store_platform": "invalid-platform",
            "store_url": "https://example.com",
            "api_key": "secret",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db.get_integration(user_id, "ecommerce") is None


def test_ecommerce_settings_reject_non_https_store_url(client, user_id):
    login(client, user_id)

    response = client.post(
        "/integrations/ecommerce",
        data={
            "store_platform": "shopify",
            "store_url": "http://example.com",
            "api_key": "secret",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert db.get_integration(user_id, "ecommerce") is None
