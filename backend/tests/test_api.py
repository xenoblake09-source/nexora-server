"""Backend tests. They use a fake provider, so no API key or network is needed."""

import os

os.environ.setdefault("AI_PROVIDER", "stub")
os.environ.setdefault("ALLOW_STUB_PROVIDER", "1")
os.environ.setdefault("DEVICE_TOKENS", "test-token-1,test-token-2")
os.environ.setdefault("RATE_PER_MINUTE", "50")
os.environ.setdefault("RATE_PER_DAY", "200")
os.environ.setdefault("MAX_INPUT_CHARS", "500")

from fastapi.testclient import TestClient  # noqa: E402

from app import main as api  # noqa: E402
from app.providers import ProviderError  # noqa: E402
from app.sessions import RateLimiter  # noqa: E402

client = TestClient(api.app)
HEADERS = {"X-Device-Token": "test-token-1"}


class BoomProvider:
    name = "boom"
    model = "boom"

    def __init__(self, kind):
        self.kind = kind

    async def reply(self, system_prompt, messages):
        raise ProviderError(self.kind)


def test_health_never_leaks_secrets():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "key" not in str(body).lower()


def test_chat_requires_token():
    assert client.post("/v1/chat", json={"text": "hello"}).status_code == 401
    assert client.post("/v1/chat", json={"text": "hello"},
                       headers={"X-Device-Token": "wrong"}).status_code == 401


def test_chat_answers_and_keeps_session_context():
    first = client.post("/v1/chat", json={"text": "मेरा रोबोट कैसा है"}, headers=HEADERS)
    assert first.status_code == 200
    body = first.json()
    assert body["language"] == "hi"
    assert body["reply"].strip()
    session = body["session_id"]

    second = client.post("/v1/chat", json={"text": "Mera robot theek hai", "session_id": session},
                         headers=HEADERS)
    assert second.status_code == 200
    assert second.json()["session_id"] == session
    assert second.json()["language"] == "hinglish"

    history = api.sessions.history(session)[1]
    assert [m["role"] for m in history][-2:] == ["user", "assistant"]


def test_input_limits_are_enforced():
    assert client.post("/v1/chat", json={"text": "   "}, headers=HEADERS).status_code == 422
    assert client.post("/v1/chat", json={"text": "a" * 501}, headers=HEADERS).status_code == 422


def test_rate_limit_blocks_after_configured_minute_quota():
    original = api.limiter
    try:
        api.limiter = RateLimiter(per_minute=2, per_day=10)
        token_headers = {"X-Device-Token": "test-token-2"}
        codes = [client.post("/v1/chat", json={"text": "hi"}, headers=token_headers).status_code
                 for _ in range(3)]
        assert codes == [200, 200, 429]
        blocked = client.post("/v1/chat", json={"text": "hi"}, headers=token_headers)
        assert blocked.json()["detail"] == "rate_limited"
        assert blocked.json()["retry_after_s"] > 0
    finally:
        api.limiter = original


def test_provider_failures_map_to_honest_status_codes():
    original = api._provider
    original_limiter = api.limiter
    try:
        api.limiter = RateLimiter(per_minute=50, per_day=200)
        api._provider = BoomProvider(ProviderError.TIMEOUT)
        assert client.post("/v1/chat", json={"text": "hello"},
                           headers={"X-Device-Token": "test-token-1"}).status_code == 504
        api._provider = BoomProvider(ProviderError.RATE_LIMIT)
        assert client.post("/v1/chat", json={"text": "hello"},
                           headers={"X-Device-Token": "test-token-1"}).status_code == 429
        api._provider = BoomProvider(ProviderError.AUTH)
        assert client.post("/v1/chat", json={"text": "hello"},
                           headers={"X-Device-Token": "test-token-1"}).status_code == 502
    finally:
        api._provider = original
        api.limiter = original_limiter


def test_server_refuses_when_no_tokens_are_configured():
    original = api.settings
    try:
        api.settings = type(original)(**{**original.__dict__, "device_tokens": ()})
        assert client.post("/v1/chat", json={"text": "hello"},
                           headers=HEADERS).status_code == 503
    finally:
        api.settings = original


def test_forget_session_requires_token_and_clears_context():
    assert client.delete("/v1/session/whatever").status_code == 401

    created = client.post("/v1/chat", json={"text": "hello there"}, headers=HEADERS)
    assert created.status_code == 200
    session = created.json()["session_id"]
    assert api.sessions.history(session)[1]  # context was stored

    cleared = client.delete(f"/v1/session/{session}", headers=HEADERS)
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "forgotten"
    assert api.sessions.history(session)[1] == []  # fresh topic, old context gone

    # Idempotent: the phone may retry the reset, which must not be an error.
    assert client.delete(f"/v1/session/{session}", headers=HEADERS).status_code == 200


def test_openai_alias_is_normalized_and_points_at_openai(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.provider == "openai_compatible"
        assert settings.provider_ready is True
        assert settings.openai_base_url == "https://api.openai.com/v1"
    finally:
        get_settings.cache_clear()


def test_payload_fits_the_chosen_model_family():
    from app.providers import OpenAiCompatibleProvider

    classic = OpenAiCompatibleProvider("k", "gpt-4o-mini", "https://api.openai.com/v1", 10.0, 220)
    classic_payload = classic.payload("sys", [{"role": "user", "content": "hi"}])
    assert classic_payload["max_tokens"] == 220
    assert classic_payload["temperature"] == 0.6

    reasoning = OpenAiCompatibleProvider("k", "gpt-5-mini", "https://api.openai.com/v1", 10.0, 220)
    reasoning_payload = reasoning.payload("sys", [{"role": "user", "content": "hi"}])
    assert "max_tokens" not in reasoning_payload
    assert reasoning_payload["max_completion_tokens"] >= 2000
    assert "temperature" not in reasoning_payload

    groq_oss = OpenAiCompatibleProvider("k", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1", 10.0, 220)
    oss_payload = groq_oss.payload("sys", [{"role": "user", "content": "hi"}])
    assert "max_tokens" not in oss_payload
    assert oss_payload["max_completion_tokens"] >= 2000
    assert oss_payload["reasoning_effort"] == "low"
    assert "temperature" not in oss_payload


class FixedProvider:
    """Test provider that returns exactly the text we want to inspect."""

    name = "fixed"
    model = "fixed"

    def __init__(self, text):
        self.text = text

    async def reply(self, system_prompt, messages):
        return self.text


def test_reply_is_cleaned_for_speech_and_language_matches_the_reply():
    original = api._provider
    try:
        api._provider = FixedProvider(
            '**Jawab** hai: 4 \u2014 jaldi! \U0001F600\n\nAur kuch? \u201cTheek hai\u201d')
        body = client.post("/v1/chat", json={"text": "2 plus 2 kitna hota hai"}, headers=HEADERS).json()
        assert body["reply"] == "Jawab hai: 4, jaldi! Aur kuch? Theek hai"
        assert body["language"] == "hinglish"  # reply Roman Hindi hai

        api._provider = FixedProvider("मैं ठीक हूँ। तुम कैसे हो?")
        body = client.post("/v1/chat", json={"text": "kaise ho"}, headers=HEADERS).json()
        assert body["language"] == "hi"  # Devanagari jawaab -> phone Hindi voice chunega

        api._provider = FixedProvider("I am fine. How are you?")
        body = client.post("/v1/chat", json={"text": "how are you"}, headers=HEADERS).json()
        assert body["language"] == "en"
    finally:
        api._provider = original

def test_live_info_triggers_and_negatives():
    from app.websearch import city_from_text, news_query, wants_live_info, weather_text

    assert wants_live_info("aaj ka mausam kaisa hai") is True
    assert wants_live_info("aaj ki taaza khabar sunao") is True
    assert wants_live_info("IPL 2026 kaun jeeta") is True
    assert wants_live_info("search karo delhi me kitni garmi hai") is True
    assert wants_live_info("2 plus 2 kitna hota hai") is False
    assert wants_live_info("mujhe ek joke sunao") is False

    assert city_from_text("delhi ka mausam", "Patna") == "Delhi"
    assert city_from_text("mausam kaisa hai", "Patna") == "Patna"

    # Weather code 0 = clear sky (pehle falsy-bug se "unclear" aa raha tha).
    assert "clear sky" in weather_text("Patna", {"temperature_2m": 31, "weather_code": 0}, {})
    # News query chhota aur taaza (when:2d) hona chahiye.
    q = news_query("Hey Nexora, aaj ki taaza khabar sunao")
    assert q.endswith("when:2d") and "khabar" not in q


class CapturingProvider:
    """Saves the system prompt so tests can check what the brain was told."""

    name = "capture"
    model = "capture"

    def __init__(self):
        self.prompts = []

    async def reply(self, system_prompt, messages):
        self.prompts.append(system_prompt)
        return "ठीक है।"


def test_live_context_reaches_the_prompt_only_when_needed(monkeypatch):
    async def fake_live(text, city, timeout=8.0):
        return "- Live weather (Open-Meteo): Patna weather right now: 31 C, clear sky"

    monkeypatch.setattr(api, "live_context", fake_live)
    original = api._provider
    capture = CapturingProvider()
    api._provider = capture
    try:
        body = client.post("/v1/chat", json={"text": "aaj patna ka mausam kaisa hai"},
                           headers=HEADERS).json()
        assert body["live"] is True
        assert body["research"]["status"] == "verified"
        assert body["research"]["sources"][0]["title"] == "Open-Meteo"
        assert "VERIFIED LIVE RESEARCH PACKET" in capture.prompts[0] and "31 C" in capture.prompts[0]
        assert body["reply"].endswith("Source: Open-Meteo.")

        body = client.post("/v1/chat", json={"text": "2 plus 2 kitna hota hai"},
                           headers=HEADERS).json()
        assert body["live"] is False
        assert "VERIFIED LIVE RESEARCH PACKET" not in capture.prompts[1]

        async def no_live(text, city, timeout=8.0):
            return None

        monkeypatch.setattr(api, "live_context", no_live)
        prompts_before = len(capture.prompts)
        body = client.post("/v1/chat", json={"text": "latest weather in Patna"}, headers=HEADERS).json()
        assert body["research"]["status"] == "unavailable"
        assert body["reply"] == api.LIVE_UNAVAILABLE_REPLY
        assert len(capture.prompts) == prompts_before  # do not let the model guess a live result
    finally:
        api._provider = original

# ---------------------------------------------------------------- camera (vision)


class FakeVision:
    name = "fake-vision"
    model = "fake-vision-model"

    def __init__(self, text="Yeh ek laal ball hai."):
        self.text = text
        self.calls = []

    async def vision_reply(self, system_prompt, question, image_b64, mime="image/jpeg"):
        self.calls.append((question, len(image_b64), mime))
        return self.text


def jpeg_b64(size=4000):
    import base64

    return base64.b64encode(b"\xff\xd8\xff" + b"x" * size).decode()


def test_vision_needs_token_and_good_image():
    assert client.post("/v1/vision", json={"text": "ye kya hai", "image_b64": jpeg_b64()}).status_code == 401
    headers = {"X-Device-Token": "test-token-1"}
    # Galat (JPEG/PNG nahi) bytes
    import base64

    bad = base64.b64encode(b"not-an-image" * 200).decode()
    assert client.post("/v1/vision", json={"image_b64": bad}, headers=headers).status_code == 422
    # Bahut badi tasveer
    huge = base64.b64encode(b"\xff\xd8\xff" + b"y" * 400000).decode()
    too_big = client.post("/v1/vision", json={"image_b64": huge}, headers=headers)
    assert too_big.status_code == 413 and too_big.json()["detail"] == "image_too_large"


def test_vision_answers_and_cleans_reply():
    original = api._vision
    fake = FakeVision("**Yeh** ek laal ball hai \u2014 gol! \U0001F600")
    api._vision = fake
    try:
        response = client.post("/v1/vision",
                               json={"text": "ye kya hai", "image_b64": jpeg_b64()},
                               headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["reply"] == "Yeh ek laal ball hai, gol!"
        assert body["vision"] is True
        assert body["model"] == "fake-vision-model"
        assert fake.calls and fake.calls[0][2] == "image/jpeg"
        # Tasveer kabhi save nahi hoti; sirf ek nishaan history me jaata hai.
        history = api.sessions.history(body["session_id"])[1]
        assert history[-2]["content"].startswith("[photo]")
    finally:
        api._vision = original


def test_vision_can_be_disabled(monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(api, "settings", replace(api.settings, vision_enabled=False))
    response = client.post("/v1/vision", json={"image_b64": jpeg_b64()}, headers=HEADERS)
    assert response.status_code == 503 and response.json()["detail"] == "vision_disabled"


def test_vision_router_tries_next_model_when_one_is_retired(monkeypatch):
    from app.providers import ProviderError, VisionRouter

    class Settings:
        provider = "openai_compatible"
        openai_api_key = "k"
        openai_base_url = "https://example.invalid/v1"
        gemini_api_key = ""
        gemini_base_url = ""
        vision_timeout_s = 5.0
        max_reply_tokens = 220
        vision_models = ("retired-model", "working-model")

    router = VisionRouter(Settings())
    tried = []

    class FakeClient:
        def __init__(self, model):
            self.model = model

        async def vision_reply(self, *args, **kwargs):
            tried.append(self.model)
            if self.model == "retired-model":
                raise ProviderError(ProviderError.MODEL_NOT_FOUND, "404")
            return "sab theek"

    monkeypatch.setattr(router, "_build", lambda model: FakeClient(model))
    import asyncio

    assert asyncio.run(router.vision_reply("sys", "q", "img")) == "sab theek"
    assert tried == ["retired-model", "working-model"]
    assert router.model == "working-model"  # chala hua model yaad rah gaya


def test_user_name_is_used_in_the_prompt_but_never_stored_on_the_server():
    original = api._provider
    capture = CapturingProvider()
    api._provider = capture
    try:
        body = client.post("/v1/chat", json={"text": "hello", "user_name": "Aarav"},
                           headers=HEADERS).json()
        assert "Aarav" in capture.prompts[-1]
        assert body["reply"].strip()
        # Naam sirf prompt me jaata hai; server koi profile save nahi karta.
        assert not hasattr(api, "profiles")
    finally:
        api._provider = original

    # Naam ke bina prompt saaf rehta hai.
    api._provider = capture
    try:
        client.post("/v1/chat", json={"text": "hello"}, headers=HEADERS)
        assert "The user's name is" not in capture.prompts[-1]
    finally:
        api._provider = original


def test_office_questions_use_live_info():
    from app.websearch import office_query, wants_live_info, wants_office

    assert wants_office("who is the chief minister of bihar") is True
    assert wants_office("bihar ke मुख्यमंत्री kaun hai") is True
    assert wants_live_info("who is the chief minister of bihar") is True
    assert wants_office("2 plus 2 kitna hota hai") is False
    # News/Wikipedia par sahi natija dene ke liye query ENGLISH keywords me honi chahiye.
    assert office_query("Hey Nexora, who is the chief minister of Bihar?") == "bihar chief minister"


def test_language_detection_covers_indian_scripts():
    from app.sessions import guess_language

    assert guess_language("मैं ठीक हूँ") == "hi"
    assert guess_language("আমি ভালো আছি") == "bn"
    assert guess_language("நான் நலமாக இருக்கிறேன்") == "ta"
    assert guess_language("నేను బాగున్నాను") == "te"
    assert guess_language("ನಾನು ಚೆನ್ನಾಗಿದ್ದೇನೆ") == "kn"
    assert guess_language("ഞാൻ സുഖമാണ്") == "ml"
    assert guess_language("હું મજામાં છું") == "gu"
    assert guess_language("ਮੈਂ ਠੀਕ ਹਾਂ") == "pa"
    assert guess_language("I am fine") == "en"
    assert guess_language("Main theek hoon") == "hinglish"


def test_office_query_always_english_keywords():
    from app.websearch import office_query

    assert office_query("who is the chief minister of bihar") == "bihar chief minister"
    assert office_query("बिहार के मुख्यमंत्री कौन है") == "bihar chief minister"
    assert office_query("Bihar ke mukhyamantri kaun hai") == "bihar chief minister"
    assert office_query("up ke cm kaun hai") == "uttar pradesh chief minister"
    assert office_query("who is the prime minister of india") == "india prime minister"
    assert office_query("झारखंड के मुख्यमंत्री कौन है") == "jharkhand chief minister"


def test_voice_map_has_male_voice_for_every_supported_language():
    from app.tts import VOICE_BY_LANGUAGE, voice_for

    for code in ["hi", "hinglish", "en", "bn", "ta", "te", "mr", "gu", "kn", "ml", "ur"]:
        assert voice_for(code), code
        assert "Neural" in VOICE_BY_LANGUAGE[code] or code in {"hinglish"}
    # BCP-47 tag bhi chalta hai (app "hi-IN" bhej sakta hai)
    assert voice_for("hi-IN") == VOICE_BY_LANGUAGE["hi"]
    assert voice_for("ta-IN") == VOICE_BY_LANGUAGE["ta"]
    assert voice_for("hinglish") == VOICE_BY_LANGUAGE["hinglish"]
    # Punjabi/Odia ka neural voice nahi hai -> app apni phone voice use karega.
    assert voice_for("pa") is None
    assert voice_for("or") is None


def test_speech_endpoint_returns_mp3_and_falls_back_honestly():
    import base64

    from app import tts

    original = tts.synthesize

    async def fake(text, language, *, rate, pitch, timeout=15.0, volume="+0%"):
        assert rate and pitch  # mood settings aage bheje jaate hain
        return b"ID3-fake-mp3-bytes", tts.voice_for(language) or "?"

    tts.synthesize = fake
    try:
        assert client.post("/v1/speech", json={"text": "namaste"}).status_code == 401
        response = client.post("/v1/speech", json={"text": "namaste sir", "language": "hi"},
                               headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True and body["mime"] == "audio/mpeg"
        assert base64.b64decode(body["audio_b64"]) == b"ID3-fake-mp3-bytes"
        # Jis bhasha ka voice nahi, wahan saaf "no_voice" - app phone ki voice chala lega.
        no_voice = client.post("/v1/speech", json={"text": "sat sri akal", "language": "pa"},
                               headers=HEADERS)
        assert no_voice.json() == {"ok": False, "reason": "no_voice"}
    finally:
        tts.synthesize = original


def test_health_reports_speech_status():
    body = client.get("/health").json()
    assert "speech" in body and isinstance(body["speech"], bool)
    assert "hi" in body["speech_voices"]


def test_office_parts_and_query_stay_english():
    from app.websearch import office_parts, office_query

    assert office_parts("Bihar ke mukhyamantri kaun hai") == ("chief minister", "bihar")
    assert office_parts("बिहार के मुख्यमंत्री कौन है") == ("chief minister", "bihar")
    assert office_parts("who is the prime minister of india") == ("prime minister", "india")
    assert office_parts("mausam kaisa hai") is None
    assert office_query("Bihar ke mukhyamantri kaun hai") == "bihar chief minister"


def test_wikipedia_infobox_incumbent_is_read_correctly():
    from app.websearch import _incumbent_name, _page_wikitext

    payload = {"query": {"pages": {"123": {"revisions": [
        {"slots": {"main": {"*": "{{Infobox officeholder\n| incumbent = [[Samrat Choudhary]]\n| since = 2026\n}}"}}}]}}}}
    text = _page_wikitext(payload)
    assert _incumbent_name(text) == "Samrat Choudhary"
    # Display text wala link: [[Narendra Modi|Modi]] -> Modi
    assert _incumbent_name("| incumbent = [[Narendra Modi|Modi]]\n") == "Modi"
    # Ref/comment hata kar saaf naam
    assert _incumbent_name("| incumbent = Samrat Choudhary<ref name=a/>\n") == "Samrat Choudhary"
    # Field hi nahi ho to None (jhooth nahi bolega)
    assert _incumbent_name("| something = else\n") is None
    assert _page_wikitext({}) == ""


def test_wikidata_incumbent_picks_the_sitting_holder():
    from app.websearch import _wd_incumbent

    rows = [
        {"mainsnak": {"datavalue": {"value": {"id": "Q_OLD"}}},
         "qualifiers": {"P580": [{"datavalue": {"value": {"time": "+2017-07-01T00:00:00Z"}}}],
                        "P582": [{"datavalue": {"value": {"time": "+2026-01-01T00:00:00Z"}}}]}},
        {"mainsnak": {"datavalue": {"value": {"id": "Q_NEW"}}},
         "qualifiers": {"P580": [{"datavalue": {"value": {"time": "+2026-04-15T00:00:00Z"}}}]}},
    ]
    assert _wd_incumbent(rows) == ("Q_NEW", "2026")
    # Sabhi khatam ho gaye: sabse naya chuno (phir bhi jhoothi baat nahi)
    ended = [dict(rows[0])]
    assert _wd_incumbent(ended) == ("Q_OLD", "2017")
    assert _wd_incumbent([]) is None


def test_party_questions_are_detected():
    """Party/sarkar wale sawaal par Live fact me party ka naam bhi aata hai."""
    from app import websearch

    assert websearch.wants_party("bihar me kaun si party ki sarkar hai")
    assert websearch.wants_party("बिहार में किस पार्टी की सरकार है")
    assert websearch.wants_party("which party is in government in bihar")
    assert not websearch.wants_party("bihar ke mukhyamantri kaun hai")
    assert not websearch.wants_party("2 plus 2")


def test_party_name_comes_from_infobox():
    from app import websearch

    wikitext = "{{Infobox officeholder\n| incumbent = [[Samrat Choudhary|Samrat]]\n| party = [[Bharatiya Janata Party|BJP]]\n}}"
    assert websearch.party_from_wikitext(wikitext) == "Bharatiya Janata Party"
    assert websearch.party_from_wikitext("| party = Indian National Congress<ref>x</ref>") == "Indian National Congress"
    assert websearch.party_from_wikitext("| name = something") is None


def test_creator_rule_is_in_prompt():
    """Server ka prompt: banane waale ka naam Arnav, Divya aur Aryan hai."""
    from app.config import DEFAULT_SYSTEM_PROMPT

    assert "Arnav, Divya and Aryan" in DEFAULT_SYSTEM_PROMPT
    assert "Never name OpenAI" in DEFAULT_SYSTEM_PROMPT
    from app.main import LIVE_PROMPT_SUFFIX

    assert "do not invent citations" in LIVE_PROMPT_SUFFIX.lower()


def test_live_context_office_question_never_breaks(monkeypatch):
    """Aaj ke bug ka offline test: live_context me chhota typo poore CM/PM jawaab ko gayab
    kar deta tha. Ab check hota hai ki office sawaal par source lagte hain (party bhi jab
    poocha ho) aur "leader kis party se hai" wale sawaal par party line aati hai.
    """
    import asyncio

    from app import websearch

    calls = {}

    async def fake_sparql(office, place, timeout=5.0, want_party=True):
        calls["sparql"] = (office, place, want_party)
        party = ", of the Bharatiya Janata Party" if want_party else ""
        return (f"Live fact (Wikidata): the current {office.title()} of {place.title()} "
                f"is Samrat Choudhary{party}, in office since 2026.")

    async def fake_wiki(office, place, timeout=8.0, want_party=False):
        calls["wiki"] = want_party
        return None

    async def fake_old_wd(office, place, timeout=8.0, want_party=False):
        calls["wd"] = want_party
        return None

    async def fake_person_party(subject, timeout=5.0):
        calls["person"] = subject
        return [f"Live fact: the party of {subject.title()} is Janata Dal (United)."]

    async def fake_news(query, timeout, limit=4, freshness="2d"):
        return []

    async def fake_wiki_lines(query, timeout, limit=2):
        return []

    monkeypatch.setattr(websearch, "wikidata_sparql_line", fake_sparql)
    monkeypatch.setattr(websearch, "wiki_incumbent_line", fake_wiki)
    monkeypatch.setattr(websearch, "wikidata_office_line", fake_old_wd)
    monkeypatch.setattr(websearch, "person_party_context", fake_person_party)
    monkeypatch.setattr(websearch, "news_lines", fake_news)
    monkeypatch.setattr(websearch, "wiki_lines", fake_wiki_lines)

    out = asyncio.run(websearch.live_context("bihar ke mukhyamantri kaun hai", "Patna"))
    assert out and "Samrat Choudhary" in out
    assert calls["sparql"][:2] == ("chief minister", "bihar")

    out2 = asyncio.run(websearch.live_context("bihar me kis party ki sarkar hai", "Patna"))
    assert out2 and "Bharatiya Janata Party" in out2
    assert calls["sparql"][2] is True                 # party sawaal: party bhi maango

    calls.clear()
    out3 = asyncio.run(websearch.live_context("nitish kumar kis party ke hain", "Patna"))
    assert out3 and "Janata Dal" in out3
    assert calls.get("person") == "nitish kumar"       # naam saaf nikla


def test_current_office_queries_do_not_silently_use_a_stored_snapshot(monkeypatch):
    """If recognised current sources fail, NEX must report uncertainty rather than a dated name."""
    import asyncio

    from app import websearch

    async def dead(*args, **kwargs):
        return None

    async def dead_list(*args, **kwargs):
        return []

    for name in ("_wikitext_for", "wikidata_sparql_line", "wiki_incumbent_line",
                 "wikidata_office_line"):
        monkeypatch.setattr(websearch, name, dead)
    monkeypatch.setattr(websearch, "wiki_lines", dead_list)

    edu = asyncio.run(websearch.portfolio_minister_line("education", "bihar", 1.0))
    assert edu is None

    health = asyncio.run(websearch.portfolio_minister_line("health", "bihar", 1.0))
    assert health is None

    cm = asyncio.run(websearch.office_live_lines("chief minister", "bihar", 1.0, True))
    assert cm == []


def test_reply_language_defaults_to_english_without_hint():
    """Phone hint na bheje to bhi Hinglish sawaal ka jawaab English me (vc24s)."""
    from app.main import language_hint_note, script_hint

    assert script_hint("bihar ke cm kaun hai") == "en"
    assert script_hint("बिहार के मुख्यमंत्री कौन हैं") == "hi"
    assert "ENGLISH" in language_hint_note(None)
    assert "DEVANAGARI" in language_hint_note(script_hint("बिहार के मुख्यमंत्री कौन हैं"))
