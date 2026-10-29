"""NEXORA backend API.

Phone  ->  this service (HTTPS + device token)  ->  AI provider (key stays here).
Run with ONE worker because conversation context is in memory.
"""

import asyncio
import base64
import hmac
import logging
import re
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .config import BUNDLE_VERSION, get_settings
from .providers import (ProviderError, build_provider, build_vision_provider,
                        with_timeout)
from .websearch import (live_context, wants_live_info, live_source_report, netcheck)
from .research import ResearchPacket, citation_spoken_suffix, collect_live_research
from . import tts
from .sessions import RateLimiter, SessionStore, guess_language

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nexora")

settings = get_settings()
app = FastAPI(title="NEXORA AI backend", version="0.1", docs_url=None, redoc_url=None)
sessions = SessionStore(settings.session_ttl_s, settings.max_sessions, settings.max_history_messages)
limiter = RateLimiter(settings.rate_per_minute, settings.rate_per_day)
_provider = None
_vision = None


def provider():
    global _provider
    if _provider is None:
        _provider = build_provider(settings)  # raises ProviderError when not configured
    return _provider


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF"
    "\uFE0F\u200D\u2022]")
_MARKDOWN_RE = re.compile(r"[*_#`~|<>]+")
_PUNCT_MAP = str.maketrans({
    "\u2014": ", ", "\u2013": ", ", "\u2012": "-", "\u2010": "-", "\u2011": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": "", "\u201d": "", "\u2026": "...",
    "\u00a0": " ", "\u200b": "", "\u00ad": "",
})


def clean_reply(text: str) -> str:
    """Bolta hua text hi bhejna hai: emoji, markdown aur ajeeb punctuation hata do.

    Dashes/curly quotes ko phone ke TTS engines kabhi kabhi "dash" ya "quote" bol dete hain,
    isliye unhe simple characters me badal dete hain. Newlines ko space bana dete hain warna
    voice beech me lambe pause leta hai.
    """
    cleaned = text.translate(_PUNCT_MAP)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = _MARKDOWN_RE.sub("", cleaned)
    cleaned = re.sub(r"\s*\n+\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.?!;:\u0964])", r"\1", cleaned)  # "hai !" -> "hai!"
    return cleaned[:600].strip()


# A bounded, cited live-research packet is appended only after a recognised source responded.
LIVE_PROMPT_SUFFIX = (
    "\n\nVERIFIED LIVE RESEARCH PACKET:\n{info}\n"
    "Answer the current part of the user's question only from this packet. Do not add dates, "
    "names, numbers, office holders, scores, weather details, or claims that are absent from it. "
    "If the packet is incomplete, say briefly what could not be verified. Do not invent citations "
    "or claim another source. The server will attach the approved source metadata separately."
)

LIVE_UNAVAILABLE_REPLY = "I could not verify current information right now, so I will not guess."


def vision_provider():
    global _vision
    if _vision is None:
        _vision = build_vision_provider(settings)  # raises ProviderError when not configured
    return _vision


# Camera ke liye: tasveer dekh kar chhota, bolne layak jawaab. Guess nahi - sirf jo dikhe.
VISION_PROMPT = (
    "\n\nThe user pointed your camera at something and asked: \"{question}\"\n"
    "Answer ONLY about the picture in front of you, in your normal short spoken style:\n"
    "1. Name the main thing you actually see, its colour, and one useful detail. Examples: "
    "\"Yeh ek laal seb hai, table par rakha hai\" or \"Yeh ek kitaab hai, neeli jild wali\".\n"
    "2. Write what is REALLY in the photo. Do not add anything that is not visible - no invented "
    "objects, no brand names, no names of people, no stories.\n"
    "3. If the photo is dark, blurry, empty or you cannot make out the main thing clearly, say "
    "honestly in ONE short sentence that you cannot see it properly (for example \"Mujhe theek se "
    "nazar nahi aa raha, thoda saamne laao\"). Never guess and never describe a different thing.\n"
    "4. If the question asks something about the photo (\"ye kya hai\", \"is ka rang kya hai\"), "
    "answer that first; if the question cannot be answered from the photo, say so in one sentence.\n"
    "5. Never say who a person is. Follow the same length, language and no-emoji rules as before."
)


# Phone batata hai kis script me jawaab chahiye ("en" / "hi" / "hinglish") - isse robot
# apne aap Hindi (Devanagari) me switch nahi karta.
_LANGUAGE_HINT_NOTE = {
    "en": ("\n\nIMPORTANT: the user spoke ENGLISH. Write your answer in simple English using "
           "Latin letters only. Do not answer in Hindi and do not use Devanagari letters."),
    "hinglish": ("\n\nIMPORTANT: the user spoke Hinglish (Hindi words written in English letters). "
                 "Write your answer in the same easy Hinglish style: Hindi words in Latin letters "
                 "(like \"bilkul, main theek hoon\"). Never use Devanagari letters."),
    "hi": ("\n\nIMPORTANT: the user spoke Hindi in Devanagari. Answer in simple everyday Hindi "
           "using DEVANAGARI letters only - no Roman Hindi, no English sentences."),
}


# (vc24s) Phone hint na bheje (browser/curl test) to sawaal ki script se bhasha.
_SCRIPT_RANGES = (("\u0900-\u097f", "hi"), ("\u0980-\u09ff", "bn"), ("\u0a00-\u0a7f", "pa"),
                  ("\u0a80-\u0aff", "gu"), ("\u0b00-\u0b7f", "or"), ("\u0b80-\u0bff", "ta"),
                  ("\u0c00-\u0c7f", "te"), ("\u0c80-\u0cff", "kn"), ("\u0d00-\u0d7f", "ml"),
                  ("\u0600-\u06ff", "ur"))


def script_hint(text: str) -> str | None:
    """Sawaal kis script me hai - wahi bhasha; Latin/Roman ho to ENGLISH default."""
    for rng, code in _SCRIPT_RANGES:
        if re.search(f"[{rng}]", text or ""):
            return code
    return "en"


def language_hint_note(hint: str | None) -> str:
    """Phone ke batayi hui bhasha ka pakka niyam (khali ho to English default)."""
    key = (hint or "").strip().lower()
    if key.startswith("hing"):
        return _LANGUAGE_HINT_NOTE["hinglish"]
    if key.startswith("hi"):
        return _LANGUAGE_HINT_NOTE["hi"]
    if key.startswith("en"):
        return _LANGUAGE_HINT_NOTE["en"]
    return "" if key else _LANGUAGE_HINT_NOTE["en"]


class VisionRequest(BaseModel):
    text: str = Field(default="Yeh kya hai?", max_length=300)
    image_b64: str = Field(min_length=200, max_length=2000000)
    session_id: str | None = Field(default=None, max_length=64)
    user_name: str | None = Field(default=None, max_length=40)
    reply_language: str | None = Field(default=None, max_length=16)


class ImageProblem(Exception):
    """Tasveer galat ho to seedha, imaandaar error."""

    def __init__(self, detail: str, status: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status = status


def decode_image(image_b64: str) -> tuple[str, str]:
    """base64 JPEG/PNG check. Sirf bharosemand bytes aage jaate hain."""
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        raise ImageProblem("bad_image") from None
    if len(raw) < 1000:
        raise ImageProblem("bad_image")
    if len(raw) > settings.max_image_bytes:
        raise ImageProblem("image_too_large", 413)
    if raw.startswith(b"\xff\xd8\xff"):
        return image_b64, "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return image_b64, "image/png"
    raise ImageProblem("bad_image")


def profile_note(user_name: str | None) -> str:
    """Phone ne naam bataya ho (aur yaad rakha ho) to robot usse pyaar se bula sakta hai."""
    name = (user_name or "").strip()[:40]
    if not name:
        return ""
    return ("\n\nThe user's name is " + name +
            ". Use their name warmly once in a while, never in every sentence.")


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)
    user_name: str | None = Field(default=None, max_length=40)
    # Phone ka bhasha hint: "en" / "hi" / "hinglish" (khaali bhi ho sakta hai).
    reply_language: str | None = Field(default=None, max_length=16)


def require_device(x_device_token: str | None = Header(default=None)) -> str:
    if not settings.device_tokens:
        raise HTTPException(status_code=503, detail="server_not_configured")
    if not x_device_token:
        raise HTTPException(status_code=401, detail="missing_token")
    for known in settings.device_tokens:
        if hmac.compare_digest(known, x_device_token):
            return x_device_token
    raise HTTPException(status_code=401, detail="bad_token")


@app.get("/v1/livecheck")
async def livecheck(q: str = "", token: str | None = None,
                    x_device_token: str | None = Header(default=None)) -> dict:
    """Debug: is sawaal par kaun sa LIVE source chala aur kya nikla (server theek hai ya nahi).

    Phone se nahi, sirf browser se test karne ke liye. Token header me lagta hai:
      GET /v1/livecheck?q=bihar+me+kis+party+ki+sarkar+hai  (header: x-device-token)
    """
    # Token header me ya seedhe link me (?token=...) - browser se test karna aasan ho.
    provided = (x_device_token or token or "").strip()
    allowed = not settings.device_tokens
    for known in settings.device_tokens:
        if provided and hmac.compare_digest(known, provided):
            allowed = True
            break
    if not allowed:
        raise HTTPException(status_code=401,
                            detail="missing_token" if not provided else "bad_token")
    text = (q or "").strip()
    if not text:
        return {"error": "q khaali hai", "bundle": BUNDLE_VERSION,
                "example": "/v1/livecheck?q=bihar me kis party ki sarkar hai&token=YOUR_TOKEN"}
    return await live_source_report(text, settings.city, settings.search_timeout_s, settings.web_search)


@app.get("/v1/netcheck")
async def netcheck_route(token: str | None = None,
                         x_device_token: str | None = Header(default=None)) -> dict:
    """Debug (vc24s): server se har source ka asli status - kya block hai, saaf pata chale.

      GET /v1/netcheck?token=YOUR_TOKEN
    """
    provided = (x_device_token or token or "").strip()
    allowed = not settings.device_tokens
    for known in settings.device_tokens:
        if provided and hmac.compare_digest(known, provided):
            allowed = True
            break
    if not allowed:
        raise HTTPException(status_code=401,
                            detail="missing_token" if not provided else "bad_token")
    return {"bundle": BUNDLE_VERSION, "sources": await netcheck(6.0)}


@app.get("/health")
async def health() -> dict:
    """Unauthenticated and secret-free: tells the phone whether the brain is usable."""
    ready = settings.provider_ready
    try:
        provider()
    except ProviderError:
        ready = False
    return {
        "status": "ok",
        "provider": settings.provider,
        "model": settings.provider_model,
        "brain_ready": ready,
        "tokens_configured": bool(settings.device_tokens),
        "bundle": BUNDLE_VERSION,
        "vision": settings.vision_enabled,
        "speech": settings.tts_enabled,
        "speech_voices": sorted(tts.VOICE_BY_LANGUAGE),
        "vision_models": list(settings.vision_models)[:3],
        "sessions": sessions.session_count(),
        "time": int(time.time()),
    }


@app.post("/v1/chat")
async def chat(request: ChatRequest, token: str = Depends(require_device)) -> dict:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="empty_text")
    if len(text) > settings.max_input_chars:
        raise HTTPException(status_code=422, detail="text_too_long")

    allowed, retry_after = limiter.check(token)
    if not allowed:
        return JSONResponse(status_code=429,
                            content={"detail": "rate_limited", "retry_after_s": retry_after})

    session_id, history = sessions.history(request.session_id)
    messages = history + [{"role": "user", "content": text}]

    # Current-information requests get a bounded, allowlisted research packet. A source failure
    # is not silently replaced by model memory: the phone receives an explicit uncertainty state.
    research_requested = settings.web_search and wants_live_info(text)
    research = ResearchPacket(False, "not_requested", None, (), None, None)
    if research_requested:
        try:
            research = await asyncio.wait_for(
                collect_live_research(text, settings.city, settings.search_timeout_s, live_context),
                timeout=settings.search_timeout_s + 5.0,
            )
        except Exception:  # bounded research must never expose internal failures to the phone
            research = ResearchPacket(
                True, "unavailable", None, (),
                "Live research timed out or returned no recognised source.", None,
            )
        if research.status == "unavailable": 
            answer = LIVE_UNAVAILABLE_REPLY
            sessions.append(session_id, "user", text)
            sessions.append(session_id, "assistant", answer)
            logger.info("live research unavailable session=%s", session_id[:8])
            return {
                "reply": answer,
                "language": "en",
                "session_id": session_id,
                "model": "research-unavailable",
                "live": False,
                "research": research.public(),
            }
        logger.info("verified live research sources=%d chars=%d",
                    len(research.citations), len(research.context or ""))

    try:
        active = provider()
    except ProviderError:
        raise HTTPException(status_code=503, detail="brain_not_configured") from None

    prompt = (settings.system_prompt + profile_note(request.user_name)
              + (LIVE_PROMPT_SUFFIX.format(info=research.context) if research.status == "verified" else "")
              + language_hint_note(getattr(request, "reply_language", None) or script_hint(text)))
    try:
        answer = await with_timeout(
            active.reply(prompt, messages), settings.request_timeout_s)
    except ProviderError as exc:
        logger.warning("provider failure: %s", exc.kind)
        status = {
            ProviderError.AUTH: 502,
            ProviderError.RATE_LIMIT: 429,
            ProviderError.TIMEOUT: 504,
            ProviderError.NETWORK: 504,
            ProviderError.SERVER: 502,
            ProviderError.BAD_RESPONSE: 502,
            ProviderError.NOT_CONFIGURED: 503,
        }.get(exc.kind, 502)
        detail = "rate_limited" if exc.kind == ProviderError.RATE_LIMIT else f"provider_{exc.kind}"
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:  # noqa: BLE001 - never leak internals to the phone
        logger.exception("unexpected provider error")
        raise HTTPException(status_code=502, detail="provider_error") from None

    answer = clean_reply(answer.strip() + citation_spoken_suffix(research))
    if not answer:
        raise HTTPException(status_code=502, detail="provider_empty")

    sessions.append(session_id, "user", text)
    sessions.append(session_id, "assistant", answer)
    logger.info("chat ok session=%s chars=%d research=%s", session_id[:8], len(answer), research.status)
    return {
        "reply": answer,
        # Phone is se apni TTS voice chunta hai, aur use REPLY ka script chahiye
        # (user ke sawaal ka nahi): Devanagari jawaab -> Hindi voice, warna English voice.
        "language": guess_language(answer),
        "session_id": session_id,
        "model": active.model,
        "live": research.status == "verified",
        "research": research.public(),
    }


class SpeechRequest(BaseModel):
    """Awaaz banane ka request: text + uski bhasha (hi, hinglish, en, ta, bn ...)."""

    text: str = Field(min_length=1, max_length=600)
    language: str = Field(default="en", max_length=16)


@app.post("/v1/speech")
async def speech(request: SpeechRequest, token: str = Depends(require_device)) -> JSONResponse:
    """Text -> MP3 (male neural voice). Rate limiter yahan nahi lagta: ye /v1/chat ke
    jawaab ka aawaaz hai, aur ek jawaab ke 2-3 tukde ban sakte hain."""
    if not settings.tts_enabled:
        return JSONResponse({"ok": False, "reason": "speech_off"})
    if len(request.text) > settings.speech_max_chars:
        return JSONResponse({"ok": False, "reason": "too_long"})
    # Pehle check: is bhasha ka male voice hai bhi? Nahi to app turant phone ki voice use kare.
    if tts.voice_for(request.language) is None:
        return JSONResponse({"ok": False, "reason": "no_voice"})
    result = await tts.synthesize(request.text, request.language,
                                 rate=settings.tts_rate, pitch=settings.tts_pitch,
                                 timeout=settings.speech_timeout_s)
    if result is None:
        return JSONResponse({"ok": False, "reason": "failed"})
    audio, voice = result
    return JSONResponse({
        "ok": True,
        "voice": voice,
        "mime": "audio/mpeg",
        "bytes": len(audio),
        "audio_b64": base64.b64encode(audio).decode("ascii"),
    })

@app.post("/v1/vision")
async def vision(request: VisionRequest, token: str = Depends(require_device)) -> dict:
    """On-demand camera: ek tasveer + ek sawaal -> chhota jawaab. Tasveer kahin save nahi hoti."""
    if not settings.vision_enabled:
        raise HTTPException(status_code=503, detail="vision_disabled")

    allowed, retry_after = limiter.check(token)
    if not allowed:
        return JSONResponse(status_code=429,
                            content={"detail": "rate_limited", "retry_after_s": retry_after})
    try:
        image_b64, mime = decode_image(request.image_b64)
    except ImageProblem as problem:
        raise HTTPException(status_code=problem.status, detail=problem.detail) from None

    try:
        active = vision_provider()
    except ProviderError:
        raise HTTPException(status_code=503, detail="vision_not_configured") from None

    question = request.text.strip() or "Yeh kya hai?"
    prompt = (settings.system_prompt + VISION_PROMPT.format(question=question)
              + language_hint_note(request.reply_language or script_hint(question))
              + profile_note(request.user_name))
    session_id, _ = sessions.history(request.session_id)
    try:
        answer = await with_timeout(
            active.vision_reply(prompt, question, image_b64, mime), settings.vision_timeout_s)
    except ProviderError as exc:
        logger.warning("vision failure: %s", exc.kind)
        status = {
            ProviderError.AUTH: 502,
            ProviderError.RATE_LIMIT: 429,
            ProviderError.TIMEOUT: 504,
            ProviderError.NETWORK: 504,
            ProviderError.SERVER: 502,
            ProviderError.BAD_RESPONSE: 502,
            ProviderError.MODEL_NOT_FOUND: 503,
            ProviderError.NOT_CONFIGURED: 503,
        }.get(exc.kind, 502)
        detail = "rate_limited" if exc.kind == ProviderError.RATE_LIMIT else f"vision_{exc.kind}"
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:  # noqa: BLE001 - never leak internals to the phone
        logger.exception("unexpected vision error")
        raise HTTPException(status_code=502, detail="vision_error") from None

    answer = clean_reply(answer.strip())
    if not answer:
        raise HTTPException(status_code=502, detail="provider_empty")

    sessions.append(session_id, "user", f"[photo] {question}")
    sessions.append(session_id, "assistant", answer)
    logger.info("vision ok session=%s chars=%d", session_id[:8], len(answer))
    return {
        "reply": answer,
        "language": guess_language(answer),
        "session_id": session_id,
        "model": active.model,
        "vision": True,
    }


@app.delete("/v1/session/{session_id}")
async def forget_session(session_id: str, token: str = Depends(require_device)) -> dict:
    """Lets the phone start a fresh topic without keeping old context."""
    sessions.forget(session_id[:64])
    return {"status": "forgotten"}


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    # Small, machine-readable messages only; no stack traces, keys or provider bodies.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# ---------------------------------------------------------------- friendly home page
@app.get("/", include_in_schema=False)
async def home() -> HTMLResponse:
    """Chhota sa page: browser me khol ke turant pata chal jaata hai ki server chalu hai."""
    ready = settings.provider_ready
    try:
        provider()
    except ProviderError:
        ready = False
    dot = "#16a34a" if ready else "#dc2626"
    state = "AI BRAIN READY - bol ke dekho!" if ready else "AI key nahi mili - Render -> Environment me key daalo"
    live = "ON" if settings.web_search else "OFF"
    eyes = "ON" if settings.vision_enabled else "OFF"
    voice = "ON (male neural)" if settings.tts_enabled else "OFF"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>NEXORA server</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b1020;color:#e5e7eb;text-align:center;padding:40px">
<h1 style="margin:0 0 6px">NEXORA server chal raha hai</h1>
<p style="opacity:.7;margin:0 0 26px">provider: {settings.provider} &nbsp;|&nbsp; model: {settings.provider_model} &nbsp;|&nbsp; web search: {live} &nbsp;|&nbsp; camera vision: {eyes} &nbsp;|&nbsp; voice: {voice} &nbsp;|&nbsp; languages: 13</p>
<p style="font-size:20px"><span style="color:{dot};font-size:28px">&#9679;</span> {state}</p>
<p style="opacity:.6;margin-top:30px"><a style="color:#7dd3fc" href="/health">/health</a> par poora status JSON milta hai</p>
</body></html>"""
    return HTMLResponse(html)
