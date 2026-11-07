import re

MAX_CATALOG_LIST_ITEMS = 20


def _strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def build_product_context(products, message):
    """
    Returns (context_text, mode).
    mode is one of: 'no_store', 'specific_matches', 'catalog_list', 'no_match'

    This function NEVER invents data — it only ever returns facts already
    present in the cached `products` table, or explicitly reports that
    nothing relevant was found.
    """
    if not products:
        return None, "no_store"

    from services.product_matching_service import find_matching_products, is_catalog_listing_question

    matches = find_matching_products(message, products)

    if matches:
        lines = ["Here is the verified product information available. Only use these exact facts:"]
        for p in matches:
            description = _strip_html(p.get("description"))[:200] or "No description available."
            lines.append(
                f"- Name: {p['name']} | Price: {p['price']} | Stock: {p['stock_status']} | "
                f"SKU: {p['sku'] or 'N/A'} | Has variations: {'Yes' if p['variations'] else 'No'} | "
                f"Description: {description}"
            )
        return "\n".join(lines), "specific_matches"

    if is_catalog_listing_question(message):
        names = [p["name"] for p in products[:MAX_CATALOG_LIST_ITEMS] if p.get("name")]
        listing = ", ".join(names)
        note = f" (showing {MAX_CATALOG_LIST_ITEMS} of {len(products)} products)" if len(products) > MAX_CATALOG_LIST_ITEMS else ""
        return (
            f"Available product names{note}: {listing}. "
            "Prices and stock are not included here — ask the customer which specific product they want details on."
        ), "catalog_list"

    return None, "no_match"