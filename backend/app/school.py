"""Stage-G school retrieval from one secure, user-authorised public source or reviewed documents.

The user supplied https://montfortbagaha.org/ after the older .com source was found to be HTTP
only. NEX fetches only three fixed HTTPS pages on that exact host, never arbitrary URLs, result
lists, transfer certificates, applications, logins, faculty lists, or student information. Current
principal/schedule/affiliation claims still require explicit up-to-date evidence and are never
guessed. Administrator-reviewed documents remain an optional secure fallback.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

# Exact user-provided HTTPS origin. This is the only website source Stage G can contact.
_SCHOOL_HOST = "montfortbagaha.org"
_PUBLIC_PAGES = {
    "profile": "https://montfortbagaha.org/school-information/",
    "contact": "https://montfortbagaha.org/contact/",
    "principal": "https://montfortbagaha.org/principals-desk/",
}
_MAX_PAGE_CHARS = 180_000

# Optional document registry. A maintainer reviews an official document, creates a small
# public-only text extract, records its SHA-256 in the manifest, then deploys both together.
SCHOOL_SOURCES_DIR = Path(__file__).with_name("school_sources")
SCHOOL_MANIFEST = SCHOOL_SOURCES_DIR / "manifest.json"
_MAX_DOCUMENT_CHARS = 12_000
_ALLOWED_TOPICS = frozenset({"profile", "contact", "facilities", "principal", "affiliation", "schedule"})

# Routing contains no school facts or people. It only identifies a clear school-context request.
_SCHOOL_MARKERS = ("montfort", "my school", "our school", "my principal", "our principal")
_CONTACT_TERMS = ("contact", "phone", "email", "address", "call", "telephone")
_PRINCIPAL_TERMS = ("principal", "headmaster", "head teacher", "head of school")
_FACILITY_TERMS = ("facility", "facilities", "library", "playground", "campus", "lab", "transport")
_AFFILIATION_TERMS = ("affiliation", "affiliated", "board", "cbse", "recognition", "noc")
_SCHEDULE_TERMS = ("timetable", "schedule", "holiday", "vacation", "academic session", "school hours")
_PROFILE_TERMS = (
    "school name", "established", "founded", "foundation", "information", "about",
    "trust", "society", "montfort",
)


def wants_school_info(text: str) -> bool:
    """True only for a clearly identified question about the configured school context."""
    value = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not value or not any(marker in value for marker in _SCHOOL_MARKERS):
        return False
    terms = (_CONTACT_TERMS + _PRINCIPAL_TERMS + _FACILITY_TERMS + _AFFILIATION_TERMS +
             _SCHEDULE_TERMS + _PROFILE_TERMS)
    return any(term in value for term in terms)


def _topic(text: str) -> str:
    value = (text or "").lower()
    if any(term in value for term in _PRINCIPAL_TERMS):
        return "principal"
    if any(term in value for term in _CONTACT_TERMS):
        return "contact"
    if any(term in value for term in _FACILITY_TERMS):
        return "facilities"
    if any(term in value for term in _AFFILIATION_TERMS):
        return "affiliation"
    if any(term in value for term in _SCHEDULE_TERMS):
        return "schedule"
    return "profile"


async def _fetch_public_page(topic: str, timeout: float) -> str | None:
    """Fetch only a fixed HTTPS path; final redirects must retain the same HTTPS host."""
    page_kind = topic if topic in {"profile", "contact", "principal"} else "profile"
    url = _PUBLIC_PAGES[page_kind]
    try:
        async with httpx.AsyncClient(timeout=min(timeout, 8.0), follow_redirects=True,
                                     headers={"User-Agent": "NEX-school-retrieval/1.0"}) as client:
            response = await client.get(url)
        final = urlparse(str(response.url))
        if (response.status_code != 200 or final.scheme != "https" or final.hostname != _SCHOOL_HOST
                or len(response.text) == 0 or len(response.text) > _MAX_PAGE_CHARS):
            return None
        return response.text
    except Exception:  # no transport internals are exposed to the companion
        return None


def _page_text(markup: str) -> str:
    """Dependency-free, bounded HTML-to-text conversion for the three fixed public pages."""
    without_active = re.sub(r"<(?:script|style)[^>]*>.*?</(?:script|style)>", " ", markup,
                             flags=re.IGNORECASE | re.DOTALL)
    with_breaks = re.sub(r"<(?:br\s*/?|/p|/div|/tr|/h[1-6]|/li|/td)>" , "\n", without_active,
                         flags=re.IGNORECASE)
    plain = re.sub(r"<[^>]+>", " ", with_breaks)
    return re.sub(r"\s+", " ", html.unescape(plain).replace("\xa0", " ")).strip()


def _content_text(markup: str) -> str:
    """Use the WordPress article body, not menu/footer text that may contain unrelated names."""
    match = re.search(r'<div[^>]+class=["\'][^"\']*entry-content[^"\']*["\'][^>]*>(.*?)</div>\s*<!--\s*\.entry-content\s*-->',
                      markup, flags=re.IGNORECASE | re.DOTALL)
    return _page_text(match.group(1) if match else markup)


def _between(text: str, start: str, stops: tuple[str, ...], limit: int = 700) -> str | None:
    match = re.search(start, text, flags=re.IGNORECASE)
    if not match:
        return None
    tail = text[match.end():]
    ends = [found.start() for marker in stops
            if (found := re.search(marker, tail, flags=re.IGNORECASE))]
    value = tail[:min(ends) if ends else limit]
    value = re.sub(r"\s+", " ", value).strip(" :|-\n")
    return value[:limit] if value else None


def _short(value: str | None, limit: int = 360) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0] + "..."


def _profile_line(markup: str, question: str) -> str | None:
    text = _content_text(markup)
    value = question.lower()
    prefix = "Official HTTPS school website (Montfort School Information): "
    if any(term in value for term in _FACILITY_TERMS):
        facilities = _between(text, r"Area of School Campus",
                              (r"Transport facility", r"Mode of payment", r"Library facilities"))
        return f"{prefix}Facilities published by the school: {_short(facilities)}" if facilities else None
    if any(term in value for term in _AFFILIATION_TERMS):
        affiliation = _between(text, r"Status of affiliation",
                               (r"Name of Trust", r"Name and official address", r"Area of School Campus"))
        # The currently published extension must not be presented as live after it has expired.
        if affiliation and _has_unexpired_affiliation(affiliation):
            return f"{prefix}Published affiliation information: {_short(affiliation)}"
        return None
    if any(term in value for term in _SCHEDULE_TERMS):
        # The site publishes only broad annual periods, not a current daily timetable. Do not infer one.
        return None

    name_address = _between(text, r"Name of the School with Address", (r"Year of establishment",))
    established = _between(text, r"Year of establishment of school", (r"Whether NOC",))
    society = _between(text, r"Name of Trust/Society/Company", (r"Name and official address",))
    facts = []
    if name_address:
        # General profile answers omit email/phone; contact facts require an explicit contact question.
        facts.append(f"School listing: {_short(name_address.split('Email:')[0], 250)}")
    if established:
        facts.append(f"Published establishment date: {_short(established, 80)}")
    if society:
        facts.append(f"Published administering society: {_short(society, 180)}")
    return prefix + "; ".join(facts) if facts else None


def _has_unexpired_affiliation(value: str) -> bool:
    matched = re.search(r"(?:up\s*to|upto)\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", value, re.IGNORECASE)
    if not matched:
        return False
    try:
        return datetime.strptime(matched.group(1), "%d %B %Y").date() >= date.today()
    except ValueError:
        return False


def _contact_line(markup: str) -> str | None:
    text = _content_text(markup)
    name = re.search(r"(Montfort Senior Secondary School.*?Bihar,?\s*845\s*101)", text, re.IGNORECASE)
    email = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
    phone = re.search(r"(?:Call us\s*:\s*)?([0-9+][0-9,\-\s]{8,40})", text, re.IGNORECASE)
    parts = []
    if name:
        parts.append(re.sub(r"\s+", " ", name.group(1)))
    if email:
        parts.append(f"Email: {email.group(0)}")
    if phone:
        parts.append(f"Published phone: {re.sub(r'\s+', ' ', phone.group(1)).strip()}")
    return ("Official HTTPS school website (Montfort Contact): " + "; ".join(parts)) if parts else None


def _principal_line(markup: str) -> str | None:
    text = _content_text(markup)
    # A photo filename or welcome message does not establish a current principal. Require a
    # labelled field and reject the website's current explicit placeholder.
    if "to be updated" in text.lower():
        return None
    match = re.search(r"(?:name of (?:the )?principal|principal)\s*[:\-]\s*([A-Za-z .'-]{3,90})", text,
                      flags=re.IGNORECASE)
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group(1)).strip(" .-:")
    return f"Official HTTPS school website (Montfort Principal's Desk): Published principal: {name}"


# ----- optional, SHA-verified official document fallback --------------------
def _safe_manifest() -> list[dict[str, Any]]:
    try:
        raw = json.loads(SCHOOL_MANIFEST.read_text(encoding="utf-8"))
        documents = raw.get("documents", [])
        return documents if isinstance(documents, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _approved_text(entry: dict[str, Any], topic: str) -> str | None:
    if not isinstance(entry, dict):
        return None
    document_id, title, filename = entry.get("id"), entry.get("title"), entry.get("file")
    expected_hash, topics = entry.get("sha256"), entry.get("topics")
    if (not isinstance(document_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", document_id)
            or not isinstance(title, str) or not title.strip() or len(title) > 100
            or not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.txt", filename)
            or not isinstance(expected_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)
            or not isinstance(topics, list) or topic not in topics or not set(topics).issubset(_ALLOWED_TOPICS)):
        return None
    valid_through = entry.get("valid_through")
    if topic in {"principal", "schedule"}:
        if not isinstance(valid_through, str):
            return None
        try:
            if date.fromisoformat(valid_through) < date.today():
                return None
        except ValueError:
            return None
    path = SCHOOL_SOURCES_DIR / filename
    try:
        if path.resolve().parent != SCHOOL_SOURCES_DIR.resolve():
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) == 0 or len(data) > _MAX_DOCUMENT_CHARS or hashlib.sha256(data).hexdigest() != expected_hash:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return re.sub(r"\s+", " ", text).strip()[:_MAX_DOCUMENT_CHARS] or None


def _excerpt(text: str, question: str) -> str:
    generic = {"about", "montfort", "school", "tell", "what", "when", "where", "which", "whose", "with", "from", "that", "this", "your", "my", "our", "the", "was", "were", "is", "are"}
    words = {word[:6] for word in re.findall(r"[a-z]{3,}", question.lower()) if word not in generic}
    sentences = re.split(r"(?<=[.!?])\s+", text)
    matching = [item.strip() for item in sentences if words.intersection(
        {word[:6] for word in re.findall(r"[a-z]{3,}", item.lower())})]
    return " ".join(item for item in (matching or sentences) if item)[:1200].strip()


async def _document_context(text: str, topic: str) -> str | None:
    for entry in _safe_manifest():
        approved = _approved_text(entry, topic)
        if not approved:
            continue
        excerpt = _excerpt(approved, text)
        if excerpt:
            title = re.sub(r"\s+", " ", str(entry["title"]).strip())[:100]
            return f"Authorised school document ({title}): {excerpt}"
    return None


async def school_context(text: str, timeout: float = 8.0) -> str | None:
    """Return a bounded authorised source line or None. None means NEX must not guess."""
    if not wants_school_info(text):
        return None
    topic = _topic(text)
    markup = await _fetch_public_page(topic, timeout)
    if markup:
        if topic == "principal":
            line = _principal_line(markup)
        elif topic == "contact":
            line = _contact_line(markup)
        else:
            line = _profile_line(markup, text)
        if line:
            return line
    return await _document_context(text, topic)
