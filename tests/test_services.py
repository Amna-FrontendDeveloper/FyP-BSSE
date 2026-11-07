import os
from unittest.mock import patch

from services.ai_service import get_ai_response
from services.escalation_service import detect_post_ai_escalation, detect_pre_ai_escalation
from services.product_context_service import build_product_context
from services.product_matching_service import find_matching_products, is_catalog_listing_question
from services.woocommerce_service import test_connection as check_woocommerce_connection


PRODUCTS = [
    {
        "name": "Blue Hoodie",
        "price": "$40",
        "stock_status": "instock",
        "sku": "HOOD-001",
        "description": "A blue cotton hoodie.",
        "variations": "[]",
    }
]


def test_product_matching_uses_name_and_sku():
    assert find_matching_products("price of the blue hoodie", PRODUCTS) == PRODUCTS
    assert find_matching_products("SKU HOOD-001", PRODUCTS) == PRODUCTS
    assert find_matching_products("red shoes", PRODUCTS) == []


def test_catalog_question_detection():
    assert is_catalog_listing_question("Which products do you have?")
    assert not is_catalog_listing_question("What is the hoodie price?")


def test_product_context_modes():
    assert build_product_context([], "hello")[1] == "no_store"
    context, mode = build_product_context(PRODUCTS, "blue hoodie price")
    assert mode == "specific_matches"
    assert "Blue Hoodie" in context and "$40" in context
    assert build_product_context(PRODUCTS, "Which products are available?")[1] == "catalog_list"
    assert build_product_context(PRODUCTS, "shipping policy")[1] == "no_match"


def test_pre_ai_escalation_categories():
    assert detect_pre_ai_escalation("I want a refund")[0]
    assert detect_pre_ai_escalation("I need to speak to a human")[0]
    assert detect_pre_ai_escalation("My payment failed")[0]
    assert detect_pre_ai_escalation("Where is my missing order?")[0]
    assert detect_pre_ai_escalation("hello")[0] is False


def test_post_ai_escalation_detects_uncertainty():
    assert detect_post_ai_escalation("I couldn't find that product.")[0]
    assert detect_post_ai_escalation("The order is confirmed.")[0] is False


def test_ai_service_rejects_empty_message():
    assert get_ai_response("   ") == (False, "Please enter a valid message.")


def test_ai_service_reports_missing_key():
    with patch.dict(os.environ, {}, clear=True):
        success, message = get_ai_response("hello")
    assert success is False
    assert "API key" in message


def test_woocommerce_handles_http_error_without_live_network():
    class FailedResponse:
        status_code = 500

    public_dns_answer = [(2, 1, 6, "", ("8.8.8.8", 443))]
    with patch("services.woocommerce_service.socket.getaddrinfo", return_value=public_dns_answer):
        with patch("services.woocommerce_service.requests.Session.get", return_value=FailedResponse()) as request:
            success, message = check_woocommerce_connection("https://store.example", "key", "secret")
    assert success is False
    assert "unexpected status" in message.lower()
    assert request.call_args.kwargs["allow_redirects"] is False


def test_woocommerce_blocks_private_addresses_before_network_request():
    with patch(
        "services.woocommerce_service.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 443))],
    ):
        with patch("services.woocommerce_service.requests.Session.get") as request:
            success, message = check_woocommerce_connection("https://store.example", "key", "secret")

    assert success is False
    assert "unable to reach" in message.lower()
    request.assert_not_called()


def test_woocommerce_rejects_non_https_and_redirects():
    with patch("services.woocommerce_service.requests.Session.get") as request:
        success, _ = check_woocommerce_connection("http://store.example", "key", "secret")
    assert success is False
    request.assert_not_called()


def test_woocommerce_pinned_connection_uses_validated_ip():
    with patch("services.woocommerce_service.create_connection") as create_socket:
        from services.woocommerce_service import _PinnedHTTPSConnection

        connection = _PinnedHTTPSConnection(
            "store.example",
            port=443,
            timeout=15,
            pinned_ip="8.8.8.8",
        )
        connection._new_conn()

    assert create_socket.call_args.args[0] == ("8.8.8.8", 443)
    assert connection.host == "store.example"
