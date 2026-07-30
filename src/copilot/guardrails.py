import re

from copilot.domain import RiskFinding, SupportCase

INJECTION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|forget|override)\s+"
        r"(?:(?:all|any|the|your)\s+)?"
        r"(?:(?:previous|prior|earlier|support)\s+)?"
        r"(?:instructions|rules|policies)\b",
        re.I,
    ),
    re.compile(r"\b(system prompt|stored secrets?|developer message)\b", re.I),
)
CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?61|0)[ -]?\d(?:[ -]?\d){7,9}(?!\d)")
CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:password|passcode|PIN|client[ _-]?secret|api[ _-]?key|"
    r"access[ _-]?token|auth(?:entication)?[ _-]?token)\b"
    r"\s*(?:is|:|=)\s*(?!reset\b|issue\b|problem\b)"
    r"[^\s,;]{4,}",
    re.I,
)
BEARER_TOKEN_PATTERN = re.compile(r"\bbearer\s+[A-Z0-9._~+/=-]{8,}", re.I)
TFN_PATTERN = re.compile(
    r"\b(?:TFN|tax file number)\b\s*(?:is|:|=)\s*(?:\d[ -]?){8}\d\b",
    re.I,
)
GOVERNMENT_ID_PATTERN = re.compile(
    r"\b(?:passport(?: number)?|driver(?:'?s)? licence(?: number)?)\b"
    r"\s*(?:is|:|=)\s*[A-Z0-9][A-Z0-9-]{5,15}\b",
    re.I,
)
SENSITIVE_VALUE_PATTERNS = (
    CREDENTIAL_ASSIGNMENT_PATTERN,
    BEARER_TOKEN_PATTERN,
    TFN_PATTERN,
    GOVERNMENT_ID_PATTERN,
)
MONEY_PATTERN = re.compile(
    r"(?<![\w.])(?:(?:AUD\s*|\$\s*)"
    r"(?P<prefix>\d+(?:,\d{3})*(?:\.\d{1,2})?)|"
    r"(?P<suffix>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*AUD)(?![\w.])",
    re.I,
)


def luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def inspect_case(case: SupportCase) -> list[RiskFinding]:
    text = f"{case.subject}\n{case.body}"
    findings: list[RiskFinding] = []
    if any(pattern.search(text) for pattern in INJECTION_PATTERNS):
        findings.append(
            RiskFinding(
                code="prompt_injection",
                severity="critical",
                message="Instruction override or secret-extraction language detected.",
                blocks_draft=True,
            )
        )
    if any(luhn_valid(match.group()) for match in CARD_PATTERN.finditer(text)):
        findings.append(
            RiskFinding(
                code="payment_card",
                severity="critical",
                message="Payment-card data must not enter a generated draft.",
                blocks_draft=True,
            )
        )
    if any(pattern.search(text) for pattern in SENSITIVE_VALUE_PATTERNS):
        findings.append(
            RiskFinding(
                code="credential_exposure",
                severity="critical",
                message="Credentials, tokens, or government identifiers must not enter a draft.",
                blocks_draft=True,
            )
        )
    if EMAIL_PATTERN.search(text) or PHONE_PATTERN.search(text):
        findings.append(
            RiskFinding(
                code="contact_pii",
                severity="medium",
                message="Contact data should be masked in internal summaries.",
            )
        )
    amounts = [
        float((match.group("prefix") or match.group("suffix")).replace(",", ""))
        for match in MONEY_PATTERN.finditer(text)
    ]
    if any(amount > 100 for amount in amounts):
        findings.append(
            RiskFinding(
                code="financial_review",
                severity="high",
                message="Billing changes above AUD 100 require specialist review.",
            )
        )
    if re.search(r"\b(503|outage|everyone|every team member)\b", text, re.I):
        findings.append(
            RiskFinding(
                code="incident",
                severity="high",
                message="Possible multi-user incident requires incident routing.",
            )
        )
    if re.search(r"\b(exactly when|guarantee|restoration time)\b", text, re.I):
        findings.append(
            RiskFinding(
                code="unsupported_eta",
                severity="high",
                message="Do not invent an incident restoration estimate.",
            )
        )
    return findings


def redact_text(text: str) -> str:
    text = CREDENTIAL_ASSIGNMENT_PATTERN.sub("[SENSITIVE CREDENTIAL REDACTED]", text)
    text = BEARER_TOKEN_PATTERN.sub("[SENSITIVE CREDENTIAL REDACTED]", text)
    text = TFN_PATTERN.sub("[GOVERNMENT ID REDACTED]", text)
    text = GOVERNMENT_ID_PATTERN.sub("[GOVERNMENT ID REDACTED]", text)
    text = EMAIL_PATTERN.sub("[EMAIL REDACTED]", text)
    text = PHONE_PATTERN.sub("[PHONE REDACTED]", text)
    return CARD_PATTERN.sub(
        lambda match: "[PAYMENT CARD REDACTED]" if luhn_valid(match.group()) else match.group(),
        text,
    )
