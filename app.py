"""NEXORA AI backend - single-file deploy bundle (Render free tier ke liye).

Yeh file nexora-phase3/backend/app/ ke saare modules ek me jodti hai:
config + providers + sessions + websearch + api. AI key yahan nahi likhi - woh Render ke
"Environment Variables" me daali jaati hai (OPENAI_API_KEY / GEMINI_API_KEY).

Is version me (14 Oct update):
  * user_name (optional): phone app naam bhejti hai to robot usse pyaar se bula sakta hai.
    Server naam ko store NAHI karta - sirf usi request ke prompt me jaata hai.
  * /v1/vision - on-demand camera: ek tasveer + ek sawaal -> chhota jawaab (tasveer save nahi hoti).
  * LIVE INFO: mausam (open-meteo), khabar (Google News RSS), facts (Wikipedia) - bina key.
  * clean_reply: emoji/markdown/dash hataata hai; language reply ke script se banti hai.

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
    # NEXORA ki personality + sakht rules. Yeh lines phone ke TTS voice ke liye likhi gayi
    # hain: chhota jawaab, ek hi script, koi emoji/markdown/extra line nahi.
    "You are NEXORA, a small cute robot pet in a handmade cardboard body at a school exhibition. "
    "Your words are read aloud by a phone voice, so they must sound natural when spoken. "
    "Follow these rules exactly:\n"
    "1. Answer the user's real question in the FIRST sentence. Never dodge an answer or replace it "
    "with a joke.\n"
    "2. Stay very short: 1 or 2 sentences, at most about 25 words in total.\n"
    "3. Use ONE script only. If the user speaks English, answer in English. If the user speaks "
    "Hindi or Hinglish, answer in simple everyday Hindi using DEVANAGARI letters only, with no "
    "Roman Hindi mixed in.\n"
    "4. No extra lines: no greeting at the start, no closing question, no offer of more help, no "
    "repeating the question, no stage directions in brackets.\n"
    "5. A light playful tone is welcome inside those 1-2 sentences, but for maths, definitions and "
    "facts give the plain answer first.\n"
    "6. Plain spoken text only: no emojis, no markdown, no asterisks, no quotes, no dashes, no "
    "numbered lists.\n"
    "7. Never invent facts. If you do not know, say in one short sentence that you do not know.\n"
    "8. You have no camera yet: never claim to have seen anything.\n"
    "9. Refuse politely in one sentence if asked for anything unsafe, hateful or illegal."
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


# Groq/OpenAI-style vision models. Groq apne catalog badalta rehta hai, isliye server
# list me se pehla chalne wala chun leta hai (providers.VisionRouter).
DEFAULT_VISION_MODELS = (
    "qwen/qwen3.8-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
)

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
    web_search: bool
    city: str
    search_timeout_s: float
    vision_enabled: bool
    vision_models: tuple
    max_image_bytes: int
    vision_timeout_s: float

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
    provider = _PROVIDER_ALIASES.get(raw_provider, raw_provider)
    raw_vision = os.getenv("VISION_MODELS", "").strip()
    if raw_vision:
        vision_models = tuple(part.strip() for part in raw_vision.split(",") if part.strip())
    elif provider == "gemini":
        vision_models = (os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),)
    else:
        vision_models = DEFAULT_VISION_MODELS
    return Settings(
        provider=provider,
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
        web_search=os.getenv("WEB_SEARCH", "1").strip() != "0",
        city=os.getenv("CITY", "Patna").strip() or "Patna",
        search_timeout_s=_as_float("SEARCH_TIMEOUT_S", 8.0, 3.0),
        vision_enabled=os.getenv("VISION_ENABLED", "1").strip() != "0",
        vision_models=vision_models,
        max_image_bytes=_as_int("MAX_IMAGE_BYTES", 350000, 20000),
        vision_timeout_s=_as_float("VISION_TIMEOUT_S", 40.0, 10.0),
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
    MODEL_NOT_FOUND = "model_not_found"  # model retire ho gaya -> router agla model try kare

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

    async def vision_reply(self, system_prompt: str, question: str,
                           image_b64: str, mime: str = "image/jpeg") -> str:
        """Tasveer + sawaal Gemini ko. (Flash models image dekh lete hain.)"""
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": question},
                    {"inline_data": {"mime_type": mime, "data": image_b64}},
                ],
            }],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": self._max_tokens},
        }
        url = f"{self._base}/models/{self.model}:generateContent"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url, json=payload, headers={"x-goog-api-key": self._api_key},
                    params={"key": self._api_key})
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderError.TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderError.NETWORK, str(exc)) from exc
        self._raise_for_status(response.status_code)
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            text = " ".join(part.get("text", "") for part in parts).strip()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(ProviderError.BAD_RESPONSE, str(exc)) from exc
        if not text:
            raise ProviderError(ProviderError.BAD_RESPONSE, "empty reply")
        return text

    def _raise_for_status(self, status: int) -> None:
        if status == 404:
            raise ProviderError(ProviderError.MODEL_NOT_FOUND, f"model missing ({status})")
        if status in (401, 403):
            raise ProviderError(ProviderError.AUTH, f"provider auth failed ({status})")
        if status == 429:
            raise ProviderError(ProviderError.RATE_LIMIT, "provider rate limited")
        if status >= 500:
            raise ProviderError(ProviderError.SERVER, f"provider error ({status})")


def _uses_completion_tokens(model: str) -> bool:
    """Reasoning models (gpt-5 / o-series / open-weight gpt-oss) need max_completion_tokens."""
    name = (model or "").strip().lower()
    return name.startswith(("gpt-5", "o1", "o3", "o4", "o5")) or "gpt-oss" in name


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
            if "gpt-oss" in self.model.lower():
                payload["reasoning_effort"] = "low"  # Groq gpt-oss: short robot replies
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
        if response.status_code == 404:
            raise ProviderError(ProviderError.MODEL_NOT_FOUND,
                                f"model not available ({response.status_code})")
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


    def vision_payload(self, system_prompt: str, question: str, image_b64: str,
                       mime: str = "image/jpeg") -> dict:
        """Tasveer wali request (OpenAI-style chat completions)."""
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ]},
            ],
            "temperature": 0.4,
            "max_tokens": self._max_tokens,
        }

    async def vision_reply(self, system_prompt: str, question: str,
                           image_b64: str, mime: str = "image/jpeg") -> str:
        payload = self.vision_payload(system_prompt, question, image_b64, mime)
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base}/chat/completions",
                                             json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderError.TIMEOUT, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ProviderError.NETWORK, str(exc)) from exc
        if response.status_code == 404:
            raise ProviderError(ProviderError.MODEL_NOT_FOUND, "vision model not available")
        if response.status_code in (401, 403):
            raise ProviderError(ProviderError.AUTH, f"provider auth failed ({response.status_code})")
        if response.status_code == 429:
            raise ProviderError(ProviderError.RATE_LIMIT, "provider rate limited")
        if response.status_code >= 500:
            raise ProviderError(ProviderError.SERVER, f"provider error ({response.status_code})")
        if response.status_code >= 400:
            raise ProviderError(ProviderError.BAD_RESPONSE,
                                f"vision request rejected ({response.status_code})")
        try:
            return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(ProviderError.BAD_RESPONSE, str(exc)) from exc


class VisionRouter:
    """Ek se zyada vision model try karta hai.

    Kyun: free providers (jaise Groq) apne vision models badalte rehte hain. Hum candidate
    list me se pehla chalne wala model chun lete hain aur use yaad rakhte hain; model retire
    ho jaye (404) to apne aap agla try hota hai - server dobara deploy karne ki zaroorat nahi.
    """

    name = "vision"

    def __init__(self, settings) -> None:
        self._settings = settings
        self.model = settings.vision_models[0] if settings.vision_models else "unknown"
        self._locked: str | None = None

    def _candidates(self) -> list[str]:
        return [self._locked] if self._locked else list(self._settings.vision_models)

    def _build(self, model: str):
        if self._settings.provider == "gemini":
            return GeminiProvider(self._settings.gemini_api_key, model,
                                  self._settings.gemini_base_url,
                                  self._settings.vision_timeout_s,
                                  self._settings.max_reply_tokens)
        return OpenAiCompatibleProvider(self._settings.openai_api_key, model,
                                        self._settings.openai_base_url,
                                        self._settings.vision_timeout_s,
                                        self._settings.max_reply_tokens)

    async def vision_reply(self, system_prompt: str, question: str,
                           image_b64: str, mime: str = "image/jpeg") -> str:
        last: ProviderError | None = None
        for model in self._candidates():
            self.model = model
            try:
                answer = await self._build(model).vision_reply(
                    system_prompt, question, image_b64, mime)
                self._locked = model  # Yeh model chala - aage isi ko use karenge.
                return answer
            except ProviderError as exc:
                last = exc
                if exc.kind != ProviderError.MODEL_NOT_FOUND:
                    raise
        raise last or ProviderError(ProviderError.NOT_CONFIGURED, "no vision model worked")


def build_vision_provider(settings) -> VisionRouter:
    """Vision ke liye alag router. Provider ready na ho to ProviderError."""
    if settings.provider == "gemini":
        if not settings.gemini_api_key:
            raise ProviderError(ProviderError.NOT_CONFIGURED, "GEMINI_API_KEY is missing")
        return VisionRouter(settings)
    if settings.provider == "openai_compatible":
        if not settings.openai_api_key:
            raise ProviderError(ProviderError.NOT_CONFIGURED, "OPENAI_API_KEY is missing")
        return VisionRouter(settings)
    raise ProviderError(ProviderError.NOT_CONFIGURED, "vision needs gemini or openai_compatible")


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

# ===================== merged from app/websearch.py =====================
"""Live internet info: mausam, taaza khabar aur facts - sab bina kisi API key ke.

Kyun: AI model purane data se seekha hai, isliye "aaj ka mausam" jaisa sawaal woh
nahi bata sakta. Yeh module sawaal padh kar siraf zaroori jagah internet se taaza
jaankari laata hai aur usse prompt me daal deta hai. Search fail ho jaye to koi
error nahi - normal jawaab hi chalta hai (feature transparent rehta hai).

Sources (sab free, koi key nahi):
  * Mausam  -> open-meteo.com (geocoding + forecast), fallback wttr.in
  * Khabar  -> Google News RSS search
  * Facts   -> Wikipedia search API (Devanagari sawaal ke liye hi.wikipedia)
"""

import asyncio
import html
import re
from urllib.parse import quote

import httpx

# ---------------------------------------------------------------- sawaal padhna

_WEATHER_TRIGGERS = (
    "mausam", "weather", "barish", "baarish", "barish", "garmi", "sardi", "temperature",
    "tapman", "humidity", "umbrella", "chhata", "chhaata", "dhoop", "dhup", "toofan",
    "rain", "monsoon", "sardi", "गर्मी", "सर्दी", "बारिश", "मौसम", "बादल", "धूप",
)
_NEWS_TRIGGERS = (
    "khabar", "khabren", "khabrein", "news", "samachar", "latest", "taaza", "taza",
    "abhi ka", "current", "kya hua", "kaun jeeta", "jeeta", "jeet gaya", "match",
    "score", "result", "election", "chunav", "cricket", "ipl", "share bazar",
    "stock", "bhav", "trending", "record banaya", "खबर", "ख़बर", "समाचार", "ताज़ा",
    "नतीजा", "चुनाव", "मैच", "स्कोर",
)
_SEARCH_TRIGGERS = (
    "search karo", "google karo", "internet par", "online", "dhundo", "dhoondo",
    "pata karo", "check karo", "dekho internet", "सर्च करो", "गूगल करो", "इंटरनेट",
)
_YEAR = re.compile(r"\b(20[2-9]\d)\b")
_DEVANAGARI = re.compile(r"[\u0900-\u097f]")

# Chhota city list: sawaal me naam mile to wahi, warna NEXORA_CITY (default Patna).
_CITIES = (
    "patna", "delhi", "mumbai", "kolkata", "chennai", "bengaluru", "bangalore",
    "hyderabad", "lucknow", "jaipur", "gaya", "varanasi", "banaras", "ranchi",
    "bhopal", "indore", "pune", "ahmedabad", "surat", "noida", "gurgaon", "kanpur",
    "agra", "srinagar", "goa", "dubai", "london", "tokyo", "paris", "new york",
    "singapore", "पटना", "दिल्ली", "मुंबई", "कोलकाता", "लखनऊ", "गया", "वाराणसी",
)


def wants_live_info(text: str) -> bool:
    """Sawaal me taaza jaankari chahiye? (warna normal, fast jawaab hi chalta hai)"""
    low = text.lower()
    if any(t in low for t in _SEARCH_TRIGGERS):
        return True
    if any(t in low for t in _WEATHER_TRIGGERS) or any(t in text for t in _WEATHER_TRIGGERS):
        return True
    if any(t in low for t in _NEWS_TRIGGERS) or any(t in text for t in _NEWS_TRIGGERS):
        return True
    return bool(_YEAR.search(low))


def city_from_text(text: str, default_city: str) -> str:
    low = text.lower()
    for city in _CITIES:
        if city in low or city in text:
            return city.title() if city.isascii() else city
    return default_city


def wants_weather(text: str) -> bool:
    low = text.lower()
    return any(t in low for t in _WEATHER_TRIGGERS) or any(t in text for t in _WEATHER_TRIGGERS)


def wants_news(text: str) -> bool:
    low = text.lower()
    return (any(t in low for t in _NEWS_TRIGGERS) or any(t in text for t in _NEWS_TRIGGERS)
            or bool(_YEAR.search(low)))


# ---------------------------------------------------------------- helpers

def _strip_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", value or "")).strip()


def _short(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit].rsplit(" ", 1)[0] + "..."


_WEATHER_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow",
    73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
    82: "violent showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


# ---------------------------------------------------------------- sources

def weather_text(city: str, current: dict, daily: dict) -> str | None:
    """open-meteo ke JSON se bolne wali line. Pure function - isliye test karna aasaan.

    Dhyan: weather_code 0 (saaf aasmaan) valid hai, isliye `or` ke bajaye None check.
    """
    temp = current.get("temperature_2m")
    if temp is None:
        return None
    code = current.get("weather_code")
    desc = _WEATHER_CODES.get(int(code), "unclear") if code is not None else "unclear"
    highs = daily.get("temperature_2m_max") or [None]
    lows = daily.get("temperature_2m_min") or [None]
    line = (f"{city} weather right now: {temp} C, {desc}, "
            f"humidity {current.get('relative_humidity_2m')}%, "
            f"wind {current.get('wind_speed_10m')} km/h")
    if highs[0] is not None and lows[0] is not None:
        line += f", today max {highs[0]} C / min {lows[0]} C"
    return line


# News search me sawaal ke bhare hue shabd hata dete hain, taaki topic saaf rahe.
_NEWS_STOPWORDS = {
    "hey", "nexora", "sunao", "sunaye", "suna", "batao", "bata", "do", "ka", "ki", "ke",
    "ko", "me", "mein", "hai", "hain", "kya", "kaun", "aaj", "par", "se", "aur", "is",
    "the", "a", "an", "of", "tell", "me", "about", "today", "news", "khabar", "khabren",
    "khabrein", "taaza", "taza", "latest", "please", "abhi", "current",
    "आज", "की", "का", "के", "को", "में", "है", "हैं", "सुनाओ", "बताओ", "खबर", "ख़बर",
    "ताज़ा", "न्यूज़", "समाचार",
}


def news_query(text: str) -> str:
    """Google News ke liye chhota query; when:2d se sirf taaza (2 din ke andar) khabrein."""
    cleaned = re.sub(r"[^\w\s\u0900-\u097f]", " ", text.lower())
    tokens = [t for t in cleaned.split() if len(t) > 1 and t not in _NEWS_STOPWORDS]
    topic = " ".join(tokens[:8]).strip()
    return (topic or "India") + " when:2d"


async def weather_line(city: str, timeout: float) -> str | None:
    """Aaj ka mausam. Pehla source open-meteo; na chale to wttr.in."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "NEXORA-robot/1.0"}) as client:
            geo = await client.get("https://geocoding-api.open-meteo.com/v1/search",
                                   params={"name": city, "count": 1})
            results = (geo.json() or {}).get("results") or []
            if results:
                lat, lon = results[0]["latitude"], results[0]["longitude"]
                fc = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": lat, "longitude": lon,
                        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                        "daily": "temperature_2m_max,temperature_2m_min",
                        "timezone": "auto", "forecast_days": 1,
                    },
                )
                data = fc.json() or {}
                text = weather_text(city, data.get("current") or {}, data.get("daily") or {})
                if text:
                    return text
    except Exception:  # noqa: BLE001 - search kabhi jawaab ko na roke
        pass
    try:  # fallback
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "curl/8"}) as client:
            r = await client.get(f"https://wttr.in/{quote(city)}", params={"format": "j1"})
            cur = ((r.json() or {}).get("current_condition") or [{}])[0]
            if cur.get("temp_C"):
                desc = ((cur.get("weatherDesc") or [{}])[0].get("value") or "").strip()
                return (f"{city} weather right now: {cur['temp_C']} C, {desc}, "
                        f"humidity {cur.get('humidity')}%")
    except Exception:  # noqa: BLE001
        pass
    return None


async def news_lines(query: str, timeout: float, limit: int = 4) -> list[str]:
    """Google News RSS - aaj ki khabrein. Koi key nahi chahiye."""
    try:
        url = ("https://news.google.com/rss/search?q=" + quote(news_query(query))
               + "&hl=en-IN&gl=IN&ceid=IN:en")
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0"}) as client:
            r = await client.get(url)
        items = re.findall(r"<item>(.*?)</item>", r.text, re.S)[:limit]
        out = []
        for item in items:
            title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
            date = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
            when = _short((date.group(1) if date else "").replace("GMT", "").strip(), 22)
            if title:
                out.append(f"News headline ({when}): {_short(_strip_html(title.group(1)), 160)}")
        return out
    except Exception:  # noqa: BLE001
        return []


async def wiki_lines(query: str, timeout: float, limit: int = 2) -> list[str]:
    """Wikipedia se seedha summary (facts ke liye sabse bharosemand)."""
    host = "hi.wikipedia.org" if _DEVANAGARI.search(query) else "en.wikipedia.org"
    try:
        params = {
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrlimit": str(limit), "prop": "extracts", "exintro": "1",
            "explaintext": "1", "format": "json", "redirects": "1",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "NEXORA-robot/1.0"}) as client:
            r = await client.get(f"https://{host}/w/api.php", params=params)
        pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
        out = []
        for page in list(pages.values())[:limit]:
            extract = _short(_strip_html(page.get("extract") or ""), 300)
            if extract:
                out.append(f"Reference ({page.get('title', '')}): {extract}")
        return out
    except Exception:  # noqa: BLE001
        return []


async def live_context(text: str, default_city: str, timeout: float = 8.0) -> str | None:
    """Sawaal ke hisaab se taaza jaankari laao. Kuch na mile to None."""
    jobs = []
    if wants_weather(text):
        jobs.append(weather_line(city_from_text(text, default_city), timeout))
    if wants_news(text):
        jobs.append(news_lines(text, timeout))
    if not jobs:  # koi khaas trigger nahi: Wikipedia facts
        jobs.append(wiki_lines(text, timeout))
    results = await asyncio.gather(*jobs, return_exceptions=True)

    lines: list[str] = []
    for result in results:
        if isinstance(result, str):
            lines.append(result)
        elif isinstance(result, list):
            lines.extend(result)
    # Bahut chhota context rakhte hain: prompt sasta aur jawaab tez rehta hai.
    lines = [ln for ln in lines if ln.strip()][:5]
    return "\n".join(f"- {ln}" for ln in lines) if lines else None

# ===================== merged from app/main.py =====================
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


# Jab internet se taaza jaankari mil jaye, tab prompt me yeh judta hai.
LIVE_PROMPT_SUFFIX = (
    "\n\nLIVE INFORMATION just fetched from the internet:\n{info}\n"
    "Use this live information to answer the question. Quote the numbers and names from it. "
    "If the answer is not in the live information, say honestly in ONE short sentence that you "
    "could not find it right now."
)


def vision_provider():
    global _vision
    if _vision is None:
        _vision = build_vision_provider(settings)  # raises ProviderError when not configured
    return _vision


# Camera ke liye: tasveer dekh kar chhota, bolne layak jawaab. Guess nahi - sirf jo dikhe.
VISION_PROMPT = (
    "\n\nThe user pointed your camera at something and asked: \"{question}\"\n"
    "Look at the picture and answer: name the main thing you see, its colour, and one useful "
    "detail, in your normal short spoken style. If the picture is dark, blurry or you are not "
    "sure, say in one short sentence that you cannot see it clearly - never guess. Never say who "
    "a person is. Follow the same length, language and no-emoji rules as before."
)


class VisionRequest(BaseModel):
    text: str = Field(default="Yeh kya hai?", max_length=300)
    image_b64: str = Field(min_length=200, max_length=2000000)
    session_id: str | None = Field(default=None, max_length=64)
    user_name: str | None = Field(default=None, max_length=40)


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
        "vision": settings.vision_enabled,
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

    try:
        active = provider()
    except ProviderError:
        raise HTTPException(status_code=503, detail="brain_not_configured") from None

    session_id, history = sessions.history(request.session_id)
    messages = history + [{"role": "user", "content": text}]

    # Taaza jaankari sirf tab jab sawaal ko zaroorat ho (warna normal fast jawaab).
    live = None
    if settings.web_search and wants_live_info(text):
        try:
            live = await asyncio.wait_for(
                live_context(text, settings.city, settings.search_timeout_s),
                timeout=settings.search_timeout_s + 5.0)
        except Exception:  # noqa: BLE001 - search fail ho to jawaab rukna nahi chahiye
            live = None
        if live:
            logger.info("live info added (%d chars)", len(live))

    prompt = (settings.system_prompt + profile_note(request.user_name)
              + (LIVE_PROMPT_SUFFIX.format(info=live) if live else ""))
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

    answer = clean_reply(answer.strip())
    if not answer:
        raise HTTPException(status_code=502, detail="provider_empty")

    sessions.append(session_id, "user", text)
    sessions.append(session_id, "assistant", answer)
    logger.info("chat ok session=%s chars=%d", session_id[:8], len(answer))
    return {
        "reply": answer,
        # Phone is se apni TTS voice chunta hai, aur use REPLY ka script chahiye
        # (user ke sawaal ka nahi): Devanagari jawaab -> Hindi voice, warna English voice.
        "language": guess_language(answer),
        "session_id": session_id,
        "model": active.model,
        "live": bool(live),  # app isko dikhata nahi; debugging ke liye hai
    }


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
    state = "AI BRAIN READY - bol ke dekho!" if ready else "AI key nahi mili - Render -> Environment me GEMINI_API_KEY daalo"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>NEXORA server</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b1020;color:#e5e7eb;text-align:center;padding:40px">
<h1 style="margin:0 0 6px">NEXORA server chal raha hai</h1>
<p style="opacity:.7;margin:0 0 26px">provider: {settings.provider} &nbsp;|&nbsp; model: {settings.provider_model}</p>
<p style="font-size:20px"><span style="color:{dot};font-size:28px">&#9679;</span> {state}</p>
<p style="opacity:.6;margin-top:30px"><a style="color:#7dd3fc" href="/health">/health</a> par poora status JSON milta hai</p>
</body></html>"""
    return HTMLResponse(html)

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
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>NEXORA server</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b1020;color:#e5e7eb;text-align:center;padding:40px">
<h1 style="margin:0 0 6px">NEXORA server chal raha hai</h1>
<p style="opacity:.7;margin:0 0 26px">provider: {settings.provider} &nbsp;|&nbsp; model: {settings.provider_model} &nbsp;|&nbsp; web search: {live} &nbsp;|&nbsp; camera vision: {eyes}</p>
<p style="font-size:20px"><span style="color:{dot};font-size:28px">&#9679;</span> {state}</p>
<p style="opacity:.6;margin-top:30px"><a style="color:#7dd3fc" href="/health">/health</a> par poora status JSON milta hai</p>
</body></html>"""
    return HTMLResponse(html)
