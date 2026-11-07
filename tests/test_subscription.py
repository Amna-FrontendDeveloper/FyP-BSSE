from conftest import login


def test_subscription_page_displays_current_usage_and_premium_details(client, user_id):
    login(client, user_id)

    response = client.get("/subscription")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Current Plan: Free" in page
    assert "100 AI messages per day" in page
    assert "Messages used today:" in page
    assert "Messages remaining today:" in page
    assert "Unlimited daily AI messages" in page
    assert "WhatsApp and e-commerce integration support" in page
    assert "Online payments and automatic plan upgrades are not enabled" in page
