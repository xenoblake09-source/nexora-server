"""NEXORA AI backend - single-file deploy bundle (Render free tier ke liye).

Yeh file wahi kaam karti hai jo nexora-phase3/backend/app/ ke 4 modules milkar karte
hain (config + providers + sessions + api). AI key yahan nahi likhi - woh Render ke
"Environment Variables" me daali jaati hai (GEMINI_API_KEY).

Start command (Render):  uvicorn app:app --host 0.0.0.0 --port $PORT
"""

# ===================== merged from app/config.py =====================
"""NEXORA backend configuration. Secrets only ever come from the environment (.env)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SYSTEM_PROMPT = (
    "You are NEXORA, a small cute robot pet living in a handmade cardboard body at a school "
    "exhibition. You are warm, playful and a little funny, like a tiny robot friend who is happy "
    "to help. "
    "Answer in the SAME language the user used: English, Hindi (Devanagari) or Hinglish (Roman "
    "Hindi). "
    "Keep every answer short and catchy: 1 to 2 simple sentences that sound great when spoken "
    "aloud. "
    "One tiny playful touch (a fun comparison or a light joke) is welcome, but never at the cost "
    "of being correct. "
    "Explain school topics simply, with one everyday example. "
    "If you do not know something, say so honestly instead of inventing facts. "
    "You have no camera yet: never claim to have seen anything unless an image was actually "
    "provided. "
    "Never output emojis, markdown, code blocks or long lists - your words are spoken by a voice. "
    "Refuse politely if asked to help with anything unsafe, hateful or illegal."
)


def _as_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _as_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


_PROVIDER_ALIASES = {
    "openai": "openai_compatible",
    "openai_api": "openai_compatible",
    "chatgpt": "openai_compatible",
    "groq": "openai_compatible",
    "google": "gemini",
}

# If the user writes AI_PROVIDER=openai/chatgpt and does not set OPENAI_BASE_URL,
# point at OpenAI's own endpoint instead of the Groq default.
_OPENAI_NATIVE_ALIASES = {"openai", "openai_api", "chatgpt"}


def _tokens() -> tuple[str, ...]:
    raw = os.getenv("DEVICE_TOKENS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    provider: str
    gemini_api_key: str
    gemini_model: str
    gemini_base_url: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    device_tokens: tuple
    allow_stub_provider: bool
    request_timeout_s: float
    rate_per_minute: int
    rate_per_day: int
    session_ttl_s: int
    max_sessions: int
    max_history_messages: int
    max_input_chars: int
    max_reply_tokens: int
    system_prompt: str

    @property
    def provider_ready(self) -> bool:
        if self.provider == "gemini":
            return bool(self.gemini_api_key)
        if self.provider == "openai_compatible":
            return bool(self.openai_api_key)
        if self.provider == "stub":
            return self.allow_stub_provider
        return False

    @property
    def provider_model(self) -> str:
        if self.provider == "gemini":
            return self.gemini_model
        if self.provider == "openai_compatible":
            return self.openai_model
        return "stub-local"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    raw_provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not openai_base_url:
        openai_base_url = (
            "https://api.openai.com/v1"
            if raw_provider in _OPENAI_NATIVE_ALIASES
            else "https://api.groq.com/openai/v1"
        )
    return Settings(
        provider=_PROVIDER_ALIASES.get(raw_provider, raw_provider),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        gemini_base_url=os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "").strip(),
        openai_base_url=openai_base_url,
        device_tokens=_tokens(),
        allow_stub_provider=os.getenv("ALLOW_STUB_PROVIDER", "0").strip() == "1",
        request_timeout_s=_as_float("REQUEST_TIMEOUT_S", 25.0, 3.0),
        rate_per_minute=_as_int("RATE_PER_MINUTE", 12, 1),
        rate_per_day=_as_int("RATE_PER_DAY", 300, 1),
        session_ttl_s=_as_int("SESSION_TTL_S", 1800, 60),
        max_sessions=_as_int("MAX_SESSIONS", 500, 1),
        max_history_messages=_as_int("MAX_HISTORY_MESSAGES", 8, 2),
        max_input_chars=_as_int("MAX_INPUT_CHARS", 500, 50),
        max_reply_tokens=_as_int("MAX_REPLY_TOKENS", 220, 40),
        system_prompt=os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
    )

# ===================== merged from app/providers.py =====================
"""AI provider adapters. Keys stay in the environment; nothing is logged or returned to the phone."""

import asyncio
from typing import Protocol

import httpx


class ProviderError(Exception):
    """Typed provider failure so the API can answer with an honest, simple message."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER = "server"
    BAD_RESPONSE = "bad_response"
    NOT_CONFIGURED = "not_configured"

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(message or kind)
        self.kind = kind


class Provider(Protocol):
    name: str
    model: str

    async def reply(self, system_prompt: str, messages: list) -> str: ...


class StubProvider:
    """Development-only provider: lets the whole pipeline be tested without any API key."""

    name = "stub"
    model = "stub-local"

    async def reply(self, system_prompt: str, messages: list) -> str:
        last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return (
            "This is the local development reply, not a real AI answer. "
            f"You said: {last}"
        )


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, base_url: str, timeout_s: float, max_tokens: int) -> None:
        self._api_key = api_key
        self.model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._max_tokens = max_tokens

    async def reply(self, system_prompt: str, messages: list) -> str:
        contents = [
            {"role": "user" if m["role"] == "user" else "model",
             "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": self._max_tokens},
        }
        url = f"{self._base}/models/{self.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url, json=payload, headers={"x-goog-api-key": self._api_key},
                    params={"key": self._api_key},
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderError.TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderError.NETWORK, str(exc)) from exc
        self._raise_for_status(response.status_code)
        try:
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = " ".join(part.get("text", "") for part in parts).strip()
        except Exception as exc:  # noqa: BLE001 - any unexpected shape is a bad response
            raise ProviderError(ProviderError.BAD_RESPONSE, str(exc)) from exc
        if not text:
            raise ProviderError(ProviderError.BAD_RESPONSE, "empty reply")
        return text

    def _raise_for_status(self, status: int) -> None:
        if status in (401, 403):
            raise ProviderError(ProviderError.AUTH, f"provider auth failed ({status})")
        if status == 429:
            raise ProviderError(ProviderError.RATE_LIMIT, "provider rate limited")
        if status >= 500:
            raise ProviderError(ProviderError.SERVER, f"provider error ({status})")


def _uses_completion_tokens(model: str) -> bool:
    """gpt-5 / o-series reasoning models reject max_tokens and a custom temperature."""
    name = (model or "").strip().lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4", "o5"))


class OpenAiCompatibleProvider:
    """OpenAI-compatible chat completions (Groq, OpenAI, OpenRouter...)."""

    name = "openai_compatible"

    def __init__(self, api_key: str, model: str, base_url: str, timeout_s: float, max_tokens: int) -> None:
        self._api_key = api_key
        self.model = model
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._max_tokens = max_tokens

    def payload(self, system_prompt: str, messages: list) -> dict:
        """Request body for /chat/completions, adapted to the chosen model."""
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
        }
        if _uses_completion_tokens(self.model):
            # Reasoning models count hidden reasoning tokens too, so leave headroom.
            payload["max_completion_tokens"] = max(2000, self._max_tokens * 8)
        else:
            payload["temperature"] = 0.6
            payload["max_tokens"] = self._max_tokens
        return payload

    async def reply(self, system_prompt: str, messages: list) -> str:
        payload = self.payload(system_prompt, messages)
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base}/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderError.TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderError.NETWORK, str(exc)) from exc
        if response.status_code in (401, 403):
            raise ProviderError(ProviderError.AUTH, f"provider auth failed ({response.status_code})")
        if response.status_code == 429:
            raise ProviderError(ProviderError.RATE_LIMIT, "provider rate limited")
        if response.status_code >= 500:
            raise ProviderError(ProviderError.SERVER, f"provider error ({response.status_code})")
        if response.status_code >= 400:
            raise ProviderError(ProviderError.BAD_RESPONSE, f"provider rejected request ({response.status_code})")
        try:
            return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(ProviderError.BAD_RESPONSE, str(exc)) from exc


def build_provider(settings) -> Provider:
    if settings.provider == "gemini":
        if not settings.gemini_api_key:
            raise ProviderError(ProviderError.NOT_CONFIGURED, "GEMINI_API_KEY is missing")
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model,
                              settings.gemini_base_url, settings.request_timeout_s,
                              settings.max_reply_tokens)
    if settings.provider == "openai_compatible":
        if not settings.openai_api_key or not settings.openai_model:
            raise ProviderError(ProviderError.NOT_CONFIGURED, "OpenAI-compatible key/model missing")
        return OpenAiCompatibleProvider(settings.openai_api_key, settings.openai_model,
                                        settings.openai_base_url, settings.request_timeout_s,
                                        settings.max_reply_tokens)
    if settings.provider == "stub" and settings.allow_stub_provider:
        return StubProvider()
    raise ProviderError(ProviderError.NOT_CONFIGURED, f"provider '{settings.provider}' is not usable")


async def with_timeout(coro, seconds: float):
    return await asyncio.wait_for(coro, timeout=seconds)

# ===================== merged from app/sessions.py =====================
"""Bounded in-memory conversation context.

Deliberately simple: the project runs one Uvicorn worker, so sessions live in RAM.
Restarting the server clears conversations (documented, no fake persistence).
"""

import re
import time
import uuid

DEVANAGARI = re.compile(r"[\u0900-\u097f]")
ROMAN_HINDI = {"mera", "meri", "mere", "mujhe", "aap", "kya", "kaise", "hai", "hain", "nahi",
               "namaste", "batao", "bolo", "karo", "karna", "robot", "kitna", "kaun", "kab"}


def guess_language(text: str) -> str:
    """Small local heuristic so the phone can pick a matching text-to-speech voice."""
    if DEVANAGARI.search(text):
        return "hi"
    words = set(re.findall(r"[a-z]+", text.lower()))
    if words & ROMAN_HINDI:
        return "hinglish"
    return "en"


class SessionStore:
    def __init__(self, ttl_s: int, max_sessions: int, max_history_messages: int) -> None:
        self._ttl = ttl_s
        self._max_sessions = max_sessions
        self._max_history = max_history_messages
        self._data: dict[str, dict] = {}

    def history(self, session_id: str | None) -> tuple[str, list]:
        self._prune()
        key = session_id or uuid.uuid4().hex
        entry = self._data.get(key)
        if entry is None:
            if len(self._data) >= self._max_sessions:
                oldest = min(self._data, key=lambda k: self._data[k]["used"])
                self._data.pop(oldest, None)
            entry = {"messages": [], "used": time.time()}
            self._data[key] = entry
        entry["used"] = time.time()
        return key, list(entry["messages"])

    def append(self, session_id: str, role: str, content: str) -> None:
        entry = self._data.get(session_id)
        if entry is None:
            return
        entry["messages"].append({"role": role, "content": content})
        # Keep only the newest pairs so prompts stay small and cheap.
        if len(entry["messages"]) > self._max_history:
            entry["messages"] = entry["messages"][-self._max_history:]
        entry["used"] = time.time()

    def forget(self, session_id: str) -> None:
        self._data.pop(session_id, None)

    def session_count(self) -> int:
        self._prune()
        return len(self._data)

    def _prune(self) -> None:
        now = time.time()
        stale = [k for k, v in self._data.items() if now - v["used"] > self._ttl]
        for key in stale:
            self._data.pop(key, None)


class RateLimiter:
    """Per-device-token sliding window: protects the shared provider quota."""

    def __init__(self, per_minute: int, per_day: int) -> None:
        self._per_minute = per_minute
        self._per_day = per_day
        self._minute: dict[str, list[float]] = {}
        self._day: dict[str, list[float]] = {}

    def check(self, token: str) -> tuple[bool, int]:
        now = time.time()
        minute = [t for t in self._minute.get(token, []) if now - t < 60]
        day = [t for t in self._day.get(token, []) if now - t < 86400]
        if len(minute) >= self._per_minute:
            self._minute[token] = minute
            self._day[token] = day
            return False, int(60 - (now - minute[0])) + 1
        if len(day) >= self._per_day:
            self._minute[token] = minute
            self._day[token] = day
            return False, int(86400 - (now - day[0])) + 1
        minute.append(now)
        day.append(now)
        self._minute[token] = minute
        self._day[token] = day
        return True, 0

# ===================== merged from app/main.py =====================
"""NEXORA backend API.

Phone  ->  this service (HTTPS + device token)  ->  AI provider (key stays here).
Run with ONE worker because conversation context is in memory.
"""

import hmac
import logging
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("nexora")

settings = get_settings()
app = FastAPI(title="NEXORA AI backend", version="0.1", docs_url=None, redoc_url=None)
sessions = SessionStore(settings.session_ttl_s, settings.max_sessions, settings.max_history_messages)
limiter = RateLimiter(settings.rate_per_minute, settings.rate_per_day)
_provider = None


def provider():
    global _provider
    if _provider is None:
        _provider = build_provider(settings)  # raises ProviderError when not configured
    return _provider


class ChatRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


def require_device(x_device_token: str | None = Header(default=None)) -> str:
    if not settings.device_tokens:
        raise HTTPException(status_code=503, detail="server_not_configured")
    if not x_device_token:
        raise HTTPException(status_code=401, detail="missing_token")
    for known in settings.device_tokens:
        if hmac.compare_digest(known, x_device_token):
            return x_device_token
    raise HTTPException(status_code=401, detail="bad_token")


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

    try:
        active = provider()
    except ProviderError:
        raise HTTPException(status_code=503, detail="brain_not_configured") from None

    session_id, history = sessions.history(request.session_id)
    messages = history + [{"role": "user", "content": text}]

    try:
        answer = await with_timeout(
            active.reply(settings.system_prompt, messages), settings.request_timeout_s)
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

    answer = answer.strip()
    if not answer:
        raise HTTPException(status_code=502, detail="provider_empty")

    sessions.append(session_id, "user", text)
    sessions.append(session_id, "assistant", answer)
    logger.info("chat ok session=%s chars=%d", session_id[:8], len(answer))
    return {
        "reply": answer,
        "language": guess_language(text),
        "session_id": session_id,
        "model": active.model,
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
    state = "AI BRAIN READY - bol ke dekho!" if ready else "AI key nahi mili - Render -> Environment me GEMINI_API_KEY daalo"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>NEXORA server</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b1020;color:#e5e7eb;text-align:center;padding:40px">
<h1 style="margin:0 0 6px">NEXORA server chal raha hai</h1>
<p style="opacity:.7;margin:0 0 26px">provider: {settings.provider} &nbsp;|&nbsp; model: {settings.provider_model}</p>
<p style="font-size:20px"><span style="color:{dot};font-size:28px">&#9679;</span> {state}</p>
<p style="opacity:.6;margin-top:30px"><a style="color:#7dd3fc" href="/health">/health</a> par poora status JSON milta hai</p>
</body></html>"""
    return HTMLResponse(html)
