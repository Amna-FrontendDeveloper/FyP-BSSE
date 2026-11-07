import os

from cryptography.fernet import Fernet

import database.database as db
from conftest import login


def test_whatsapp_access_token_is_encrypted_when_saved(client, user_id, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    login(client, user_id)

    response = client.post(
        "/integrations/whatsapp",
        data={"phone_number": "+15551234567", "api_key": "whatsapp-test-access-token"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    integration = db.get_integration(user_id, "whatsapp")
    assert integration["phone_number"] == "+15551234567"
    assert integration["api_key"] != "whatsapp-test-access-token"
    assert Fernet(os.environ["APP_ENCRYPTION_KEY"].encode()).decrypt(
        integration["api_key"].encode()
    ).decode() == "whatsapp-test-access-token"
