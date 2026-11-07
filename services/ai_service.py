import os
import logging

import requests

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

AI_API_BASE_URL = os.getenv("AI_API_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "openai/gpt-oss-120b")
REQUEST_TIMEOUT_SECONDS = 20


def _build_system_prompt(product_context, context_mode):
    base_persona = "You are a helpful AI customer support assistant for an online store."

    grounding_rule = (
        "STRICT RULE: You must never invent or guess prices, stock availability, "
        "product names, sizes, delivery information, or return policies. "
        "Only state facts explicitly given to you below. If the customer asks about "
        "something not covered by the information given, clearly say you do not have "
        "that information rather than guessing."
    )

    if context_mode == "no_store":
        situational_note = (
            "No product catalog is currently connected for this business. If the "
            "customer asks about specific products, prices, stock, or SKUs, tell them "
            "that information isn't available right now."
        )
    elif context_mode == "no_match":
        situational_note = (
            "The customer appears to be asking about a specific product, but no "
            "matching product was found in the store's catalog. Do not guess — tell "
            "them you couldn't find that item and ask them to confirm the exact "
            "product name."
        )
    elif context_mode in ("specific_matches", "catalog_list"):
        situational_note = product_context
    else:
        situational_note = ""

    return f"{base_persona}\n\n{grounding_rule}\n\n{situational_note}"


def get_ai_response(message: str, product_context: str = None, context_mode: str = "no_store"):
    """
    Returns a tuple: (success, text). Unchanged contract from before —
    product_context/context_mode are optional so existing callers and
    tests that only pass `message` keep working exactly as before.
    """
    if not message or not message.strip():
        return False, "Please enter a valid message."

    api_key = os.getenv("AI_API_KEY")
    if not api_key:
        return False, "AI API key is missing. Add it to the .env file before using the AI assistant."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    system_content = _build_system_prompt(product_context, context_mode)

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": message},
        ],
        "temperature": 0.5,
        "max_tokens": 300,
    }

    try:
        response = requests.post(
            AI_API_BASE_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return True, data["choices"][0]["message"]["content"].strip()

    except requests.exceptions.Timeout:
        logger.warning("AI API request timed out.")
        return False, "The AI assistant is taking too long to respond. Please try again."

    except requests.exceptions.HTTPError as error:
        logger.warning("AI API returned an error: %s | Response body: %s", error, response.text)
        return False, "The AI service returned an error. Please try again shortly."

    except requests.exceptions.RequestException as error:
        logger.warning("AI API network error: %s", error)
        return False, "I'm unable to reach the AI service right now. Please check your internet connection."

    except (KeyError, IndexError, ValueError) as error:
        logger.warning("Unexpected AI API response format: %s", error)
        return False, "The AI service returned an unexpected response. Please try again."