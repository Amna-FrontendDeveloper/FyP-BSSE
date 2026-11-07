import re

STOPWORDS = {
    "the", "is", "a", "an", "of", "to", "for", "this", "that", "in", "on",
    "and", "or", "are", "do", "does", "what", "which", "tell", "me", "about",
    "please", "i", "want", "know", "product", "products", "item", "items",
}

CATALOG_INTENT_PHRASES = [
    "which products", "what products", "products do you have", "products are available",
    "what do you sell", "what items", "list of products", "show me your products",
    "what is available", "available products",
]


def _tokenize(text):
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def is_catalog_listing_question(message):
    lowered = message.lower()
    return any(phrase in lowered for phrase in CATALOG_INTENT_PHRASES)


def find_matching_products(message, products, max_results=3):
    """
    Keyword-overlap matching between the customer's message and cached
    product names/SKUs. Deliberately simple — no fuzzy matching or ML —
    so it's fully explainable in a viva.
    """
    query_tokens = set(_tokenize(message))
    if not query_tokens:
        return []

    scored = []
    for product in products:
        name_tokens = set(_tokenize(product.get("name") or ""))
        sku_tokens = set(_tokenize(product.get("sku") or ""))
        overlap = query_tokens & (name_tokens | sku_tokens)
        if overlap:
            scored.append((len(overlap), product))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [product for _, product in scored[:max_results]]