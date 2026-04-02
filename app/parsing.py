import re
from dataclasses import dataclass
from typing import Optional


NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
}

REQUIRED_PREFIX = r"(?:at least|minimum of|min\.?|minimum|required|required minimum|must have|must possess|need|needs|needs? at least|requires?|requiring|with)"
PREFERRED_PREFIX = r"(?:preferred|preference for|ideally|ideally has|nice to have)"

YEARS_RANGE_PATTERN = re.compile(
    r"(?P<low>\d+)\s*(?:\+)?\s*(?:-|to|through|–|—)\s*(?P<high>\d+)\+?\s*(?:years?|yrs?)",
    re.I,
)
YEARS_MIN_PATTERN = re.compile(
    r"(?P<low>\d+)(?:\+|\s+or\s+more)?\s*(?:years?|yrs?)",
    re.I,
)
YEARS_EXPERIENCE_CONTEXT = re.compile(
    r"(?P<low>\d+)(?:\+|\s+or\s+more)?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|professional experience|working experience|relevant experience|industry experience)",
    re.I,
)
YEARS_EMBEDDED_PATTERN = re.compile(
    r"(?:minimum|required|requires?|requiring|preferred|preference for)\s+(?P<low>\d+)\+?\s*(?:\w+\s+){0,6}?(?:years?|yrs?)",
    re.I,
)

# Seniority signals used as a fallback when no explicit years are found in the text.
# Each entry is (pattern, min_years, max_years).
SENIORITY_EXPERIENCE = [
    (re.compile(r"\b(junior|entry[\s-]level|associate)\b", re.I), 0, 2),
    (re.compile(r"\b(vp|vice\s+president)\b", re.I), 8, None),
    (re.compile(r"\bprincipal\b", re.I), 8, 12),
    (re.compile(r"\bstaff\b", re.I), 7, 10),
    (re.compile(r"\b(senior|sr\.?|lead)\b", re.I), 5, 8),
]


@dataclass
class ParsedExperience:
    min_years: Optional[int] = None
    max_years: Optional[int] = None


def normalize_numeric_language(text: str) -> str:
    normalized = f" {(text or '').lower()} "
    for word, value in NUMBER_WORDS.items():
        normalized = re.sub(rf"\b{word}\b", str(value), normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_amounts(text: str) -> list[int]:
    """Pull all dollar-like amounts from text, filtered to plausible salary range."""
    amounts = []
    pattern = re.compile(r"(?:USD)?\$\s*(\d{2,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kKmM])?")
    for raw_amount, suffix in pattern.findall(text):
        amount = float(raw_amount.replace(",", ""))
        suffix = suffix.lower()
        if suffix == "k":
            amount *= 1_000
        elif suffix == "m":
            amount *= 1_000_000
        amount = int(amount)
        if 50_000 <= amount <= 2_000_000:
            amounts.append(amount)
    return amounts


def _salary_from_context(text: str):
    """Find salary from text near compensation keywords — best for raw HTML."""
    salary_context = re.compile(
        r"(?:salary|compensation|pay|base|annual|range|usd)[^\n]{0,120}",
        re.I,
    )
    for match in salary_context.finditer(text):
        snippet = match.group(0)
        amounts = _extract_amounts(snippet)
        if len(amounts) >= 2:
            return min(amounts), max(amounts)
        if len(amounts) == 1:
            return amounts[0], amounts[0]

    range_pattern = re.compile(
        r"(?:USD)?\$\s*[\d,]+(?:\.\d+)?\s*[-\u2013\u2014]\s*(?:USD)?\$\s*[\d,]+(?:\.\d+)?",
        re.I,
    )
    for match in range_pattern.finditer(text):
        amounts = _extract_amounts(match.group(0))
        if len(amounts) >= 2:
            return min(amounts), max(amounts)

    return None


def parse_salary(text: str):
    normalized = normalize_numeric_language(text).replace(".00", "")
    if not normalized:
        return None

    if len(normalized) > 5000:
        return _salary_from_context(normalized)

    amounts = _extract_amounts(normalized)
    if len(amounts) >= 2:
        return min(amounts), max(amounts)
    if len(amounts) == 1:
        return amounts[0], amounts[0]
    return None


def format_salary_label(bounds) -> str:
    if not bounds:
        return ""
    low, high = bounds
    return f"${low:,.0f}" if low == high else f"${low:,.0f} – ${high:,.0f}"


def _best_candidate(candidates: list[ParsedExperience]) -> ParsedExperience:
    if not candidates:
        return ParsedExperience()
    return max(
        candidates,
        key=lambda item: (
            item.min_years if item.min_years is not None else -1,
            item.max_years if item.max_years is not None else -1,
        ),
    )


def parse_experience_years(*texts: str) -> ParsedExperience:
    combined = " ".join(normalize_numeric_language(text) for text in texts if text)
    if not combined:
        return ParsedExperience()

    required_or_general: list[ParsedExperience] = []
    preferred: list[ParsedExperience] = []

    def bucket_for(prefix: str) -> list[ParsedExperience]:
        prefix = (prefix or "").lower()
        return preferred if re.search(PREFERRED_PREFIX, prefix, re.I) else required_or_general

    for match in re.finditer(
        rf"(?P<prefix>{REQUIRED_PREFIX}|{PREFERRED_PREFIX})?[\s:,-]*(?P<low>\d+)\s*(?:\+)?\s*(?:-|to|through|–|—)\s*(?P<high>\d+)\+?\s*(?:years?|yrs?)",
        combined,
        re.I,
    ):
        bucket_for(match.group("prefix")).append(
            ParsedExperience(min_years=int(match.group("low")), max_years=int(match.group("high")))
        )

    for match in re.finditer(
        rf"(?P<prefix>{REQUIRED_PREFIX}|{PREFERRED_PREFIX})[\s:,-]*(?P<low>\d+)(?:\+|\s+or\s+more)?\s*(?:years?|yrs?)",
        combined,
        re.I,
    ):
        bucket_for(match.group("prefix")).append(ParsedExperience(min_years=int(match.group("low")), max_years=None))

    for match in YEARS_EXPERIENCE_CONTEXT.finditer(combined):
        required_or_general.append(ParsedExperience(min_years=int(match.group("low")), max_years=None))

    for match in YEARS_EMBEDDED_PATTERN.finditer(combined):
        snippet = match.group(0)
        target = preferred if re.search(PREFERRED_PREFIX, snippet, re.I) else required_or_general
        target.append(ParsedExperience(min_years=int(match.group("low")), max_years=None))

    chosen = _best_candidate(required_or_general) if required_or_general else _best_candidate(preferred)

    # Fallback: infer from seniority signals in the title (first text arg) when
    # no explicit year patterns were found anywhere in the combined text.
    if chosen.min_years is None and chosen.max_years is None and texts:
        title = texts[0] or ""
        for pattern, min_y, max_y in SENIORITY_EXPERIENCE:
            if pattern.search(title):
                chosen = ParsedExperience(min_years=min_y, max_years=max_y)
                break

    return chosen
