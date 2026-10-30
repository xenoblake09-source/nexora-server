"""Structured, citation-backed live-research packets for NEX.

The older web-search module returns compact prompt lines. This adapter turns only those
known-provider lines into safe, user-facing source metadata. It never exposes arbitrary
URLs returned by a search result, and it never calls a result "verified" without at least
one recognised source type.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable


@dataclass(frozen=True)
class Citation:
    id: str
    title: str
    url: str
    source_type: str
    current: bool
    confidence: str
    retrieved_at: str

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ResearchPacket:
    requested: bool
    status: str  # not_requested | verified | unavailable
    context: str | None
    citations: tuple[Citation, ...]
    uncertainty: str | None
    retrieved_at: str | None

    def public(self) -> dict:
        return {
            "status": self.status,
            "uncertainty": self.uncertainty,
            "retrieved_at": self.retrieved_at,
            "sources": [citation.public() for citation in self.citations],
        }


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def citations_for_context(context: str | None, retrieved_at: str | None = None) -> tuple[Citation, ...]:
    """Create citations only for named, allowlisted provider lines.

    A source label in the prompt is not enough to be exposed blindly. The URLs below are
    fixed first-party provider URLs; no search-result URL or model-provided URL reaches the app.
    """
    if not context:
        return ()
    stamp = retrieved_at or _timestamp()
    discovered: list[tuple[str, str, str, bool, str]] = []
    for raw in context.splitlines():
        line = raw.strip().lower()
        if "(wikidata)" in line:
            discovered.append(("Wikidata", "https://www.wikidata.org/", "wikidata", True, "high"))
        elif "live fact (wikipedia)" in line:
            discovered.append(("Wikipedia", "https://www.wikipedia.org/", "wikipedia", True, "medium"))
        elif line.startswith("- reference ("):
            discovered.append(("Wikipedia", "https://www.wikipedia.org/", "wikipedia", False, "medium"))
        elif line.startswith("- news headline"):
            discovered.append(("Google News RSS", "https://news.google.com/", "news", True, "medium"))
        elif "live weather (open-meteo)" in line:
            discovered.append(("Open-Meteo", "https://open-meteo.com/", "weather", True, "high"))
        elif "live weather (wttr.in)" in line:
            discovered.append(("wttr.in", "https://wttr.in/", "weather", True, "medium"))
        elif line.lstrip("- ").startswith("official https school website (montfort school information)"):
            discovered.append(("Montfort Official Website", "https://montfortbagaha.org/school-information/", "school", False, "medium"))
        elif line.lstrip("- ").startswith("official https school website (montfort contact)"):
            discovered.append(("Montfort Official Website", "https://montfortbagaha.org/contact/", "school", False, "medium"))
        elif line.lstrip("- ").startswith("official https school website (montfort principal"):
            discovered.append(("Montfort Official Website", "https://montfortbagaha.org/principals-desk/", "school", False, "medium"))
        elif line.lstrip("- ").startswith("authorised school document ("):
            # Documents are reviewed public-only extracts with a SHA-256 verified manifest entry.
            # They may have no public web URL, so the Android app renders a label but never opens one.
            discovered.append(("Authorised School Document", "", "school_document", False, "high"))

    citations: list[Citation] = []
    seen: set[str] = set()
    for title, url, source_type, current, confidence in discovered:
        if source_type in seen:
            continue
        seen.add(source_type)
        citations.append(Citation(
            id=f"S{len(citations) + 1}", title=title, url=url, source_type=source_type,
            current=current, confidence=confidence, retrieved_at=stamp,
        ))
        if len(citations) == 3:
            break
    return tuple(citations)


async def collect_live_research(
    text: str,
    default_city: str,
    timeout: float,
    collect_context: Callable[[str, str, float], Awaitable[str | None]],
) -> ResearchPacket:
    """Fetch one bounded research packet and expose uncertainty rather than guessing."""
    stamp = _timestamp()
    try:
        context = await collect_context(text, default_city, timeout)
    except Exception:  # The public result must not leak transport/provider internals.
        context = None
    citations = citations_for_context(context, stamp)
    if context and citations:
        uncertainty = None
        if any(citation.source_type in {"school", "school_document"} for citation in citations):
            uncertainty = ("Authorised school source retrieved; NEX does not treat an expired or "
                           "missing source as proof of current staff, schedules, or private student information.")
        return ResearchPacket(True, "verified", context, citations, uncertainty, stamp)
    return ResearchPacket(
        True,
        "unavailable",
        None,
        (),
        "No recognised current source responded, so NEX did not answer from static memory.",
        stamp,
    )
