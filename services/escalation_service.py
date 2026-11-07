import re

HUMAN_REQUEST_PATTERNS = [
    r"\bhuman\b", r"\bagent\b", r"\breal person\b",
    r"\bspeak to (someone|a person|a human|an agent)\b",
    r"\btalk to (someone|a person|a human|an agent)\b",
    r"\bcustomer service\b", r"\brepresentative\b", r"\bmanager\b",
]

COMPLAINT_PATTERNS = [
    r"\bcomplain(t|ing)?\b", r"\bterrible\b", r"\bawful\b", r"\bunacceptable\b",
    r"\bdisappoint(ed|ing)?\b", r"\bangry\b", r"\bfurious\b", r"\bworst\b",
]

REFUND_PATTERNS = [
    r"\brefund\b", r"\bmoney back\b", r"\breturn (my|the) (order|item|product)\b",
    r"\bcancel (my|the) order\b",
]

PAYMENT_PATTERNS = [
    r"\bpayment\b", r"\bcharged\b", r"\bcredit card\b", r"\bdouble charged\b",
    r"\btransaction failed\b", r"\bbilling\b",
]

SENSITIVE_ORDER_PATTERNS = [
    r"\bmissing (order|package|item)\b", r"\bwrong (item|order|product)\b",
    r"\bnever arrived\b", r"\bdamaged\b", r"\blost (order|package)\b",
]

AI_UNCERTAINTY_PHRASES = [
    "i don't have that information", "i do not have that information",
    "i couldn't find", "i could not find", "not available",
    "i'm unable to help", "i am unable to help",
    "i don't have access", "i do not have access",
]


def _matches_any(patterns, text):
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in patterns)


def detect_pre_ai_escalation(user_message):
    """
    Checked BEFORE the AI is called. If any of these match, the AI
    should not attempt an answer at all — the customer is handed off
    directly. Order matters: more specific/serious categories first.
    """
    if _matches_any(HUMAN_REQUEST_PATTERNS, user_message):
        return True, "Customer requested to speak with a human."
    if _matches_any(REFUND_PATTERNS, user_message):
        return True, "Possible refund request."
    if _matches_any(PAYMENT_PATTERNS, user_message):
        return True, "Possible payment issue."
    if _matches_any(SENSITIVE_ORDER_PATTERNS, user_message):
        return True, "Sensitive order problem (missing/damaged/wrong item)."
    if _matches_any(COMPLAINT_PATTERNS, user_message):
        return True, "Possible customer complaint."
    return False, None


def detect_post_ai_escalation(ai_reply):
    """
    Checked AFTER a successful AI response, to catch cases where the
    AI itself signaled it couldn't help (e.g. product not found).
    """
    if ai_reply and _matches_any(AI_UNCERTAINTY_PHRASES, ai_reply):
        return True, "AI did not have enough information to answer."
    return False, None