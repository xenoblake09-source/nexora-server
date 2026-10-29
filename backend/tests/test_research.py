"""Stage-E research packet tests: no network and no provider credentials needed."""

import asyncio

from app.config import DEFAULT_SYSTEM_PROMPT
from app.research import collect_live_research, citation_spoken_suffix, citations_for_context


def test_allowlisted_citations_are_structured_and_deduplicated():
    context = "\n".join([
        "- Live fact (Wikidata): the current example is A.",
        "- News headline (today): Example headline.",
        "- Live weather (Open-Meteo): Patna weather right now: 30 C.",
        "- Reference (Example): a reference summary.",
        "- Another Live fact (Wikidata): duplicate source.",
    ])
    sources = citations_for_context(context, "2026-10-29T00:00:00Z")
    assert [source.id for source in sources] == ["S1", "S2", "S3"]
    assert [source.source_type for source in sources] == ["wikidata", "news", "weather"]
    assert all(source.url.startswith("https://") for source in sources)
    assert all("example headline" not in source.url.lower() for source in sources)


def test_unavailable_research_never_becomes_a_verified_answer():
    async def no_source(*_args):
        return None

    packet = asyncio.run(collect_live_research("latest example", "Patna", 1.0, no_source))
    assert packet.status == "unavailable"
    assert packet.context is None
    assert packet.citations == ()
    assert "did not answer from static memory" in (packet.uncertainty or "")


def test_school_answers_require_authorized_source_not_a_hardcoded_school():
    assert "official public source" in DEFAULT_SYSTEM_PROMPT
    assert "Montfort" not in DEFAULT_SYSTEM_PROMPT
    assert "Vincent Madhanu" not in DEFAULT_SYSTEM_PROMPT


def test_verified_packet_has_deterministic_spoken_source_suffix():
    async def one_source(*_args):
        return "- Live weather (Open-Meteo): Patna weather right now: 30 C."

    packet = asyncio.run(collect_live_research("Patna weather", "Patna", 1.0, one_source))
    assert packet.status == "verified"
    assert packet.public()["sources"][0]["title"] == "Open-Meteo"
    assert citation_spoken_suffix(packet) == " Source: Open-Meteo."
