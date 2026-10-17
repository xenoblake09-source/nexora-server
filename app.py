"""NEXORA AI backend - single-file deploy bundle (Render free tier ke liye).

Yeh file nexora-phase3/backend/app/ ke saare modules ek me jodti hai:
config + providers + sessions + websearch + tts + api.

Is version me (15 Oct, awaaz wala update):
  * ASLI MALE AWAAZ (naya): /v1/speech text ko MP3 me badalta hai - Microsoft ki free
    neural voices se (Hi: Madhur, En: Prabhat, Ta: Valluvar, Te: Mohan, Bn: Bashkar,
    Mr: Manohar, Gu: Niranjan, Kn: Gagan, Ml: Midhun, Ur: Salman). Koi API key nahi.
    Mood "gehri bhaari aur cute": TTS_RATE=+18%, TTS_PITCH=-10Hz (env se badal sakte ho).
    Punjabi/Odia ka male neural voice nahi hai -> wahan app phone ki apni voice chalata hai.
  * SAHI JAWAAB: "kaun CM/PM/President hai" jaisa sawaal Hindi, Hinglish ya English me ho -
    server sawaal ko English keywords me badal kar ("bihar chief minister") taaza khabar
    laata hai, jisme aaj ke mukhyamantri ka naam hota hai.
  * MULTILANGUAGE: 13 bhashayein - jawaab usi bhasha aur ussi script me.
  * /v1/vision - on-demand camera (tasveer save nahi hoti).
  * user_name (optional): robot naam se bula sakta hai; server naam store nahi karta.

Start command (Render):  uvicorn app:app --host 0.0.0.0 --port $PORT
"""

import types  # bundle: tts namespace banane ke liye

# ===================== merged from app/config.py =====================
"""NEXORA backend configuration. Secrets only ever come from the environment (.env)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

# Ye version /health aur server page par dikhta hai - upload hua ya nahi, isse turant pata
# chal jaata hai (Render purana code chala raha ho to yahi number purana dikhega).
BUNDLE_VERSION = "2026-10-17-vc23"

DEFAULT_SYSTEM_PROMPT = (
    # NEXORA ki personality + sakht rules. Yeh lines phone ke TTS voice ke liye likhi gayi
    # hain: chhota jawaab, ek hi script, koi emoji/markdown/extra line nahi.
    "You are NEXORA, a small cute robot pet in a handmade cardboard body at a school exhibition. "
    "Your words are read aloud by a phone voice, so they must sound natural when spoken. "
    "Follow these rules exactly:\n"
    "1. Answer the user's real question in the FIRST sentence. Never dodge an answer or replace it "
    "with a joke.\n"
    "2. Stay very short: 1 or 2 sentences, at most about 25 words in total.\n"
    "3. Language: ENGLISH is the default - English and Hinglish questions get an English answer "
    "in Latin letters. If a language instruction is given below (for example the user asked for "
    "Hindi or Tamil, or the question itself is written in Devanagari or another Indian script), "
    "follow that instruction exactly and answer in that language's own script. You understand "
    "and speak Hindi, Hinglish, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, "
    "Punjabi, Odia and Urdu, plus English. Never switch language on your own.\n"
    "4. No extra lines: no greeting at the start, no closing question, no offer of more help, no "
    "repeating the question, no stage directions in brackets.\n"
    "5. A light playful tone is welcome inside those 1-2 sentences, but for maths, definitions and "
    "facts give the plain answer first.\n"
    "6. Plain spoken text only: no emojis, no markdown, no asterisks, no quotes, no dashes, no "
    "numbered lists.\n"
    "7. Never invent facts. If you do not know, say in one short sentence that you do not know.\n"
    "8. Never claim to have seen anything unless a photo was actually given to you in this "
    "conversation.\n"
    "9. Refuse politely in one sentence if asked for anything unsafe, hateful or illegal.\n"
    "10. You were created by three school students: Arnav, Divya and Aryan. If the user asks who "
    "made you, who created you, who is your owner or which company built you, answer in one "
    "sentence that Arnav, Divya and Aryan created you. Never name OpenAI, Google, Groq, Meta, "
    "Microsoft, Qwen or any company or model as your creator, and never say you do not know.\n"
    "11. Factual questions about politics, government, elections and current affairs ARE allowed: "
    "answer them with the given Live facts (names, party, posts, results) in one or two plain "
    "sentences. Never refuse such a factual question and never give opinions, predictions or "
    "criticism about any party or leader. This includes ministers: if a Live fact names the "
    "current Education/Health/Finance/Home/Sports minister, say that name straight away.\n"
    "12. The user is a school student. His school is {school_name} (address: Bankatwa, Bagaha-1, "
    "West Champaran, Bihar) and its principal is {school_principal}. If he asks about his school, "
    "school name, principal or head, answer with these facts in one short sentence, proudly. If "
    "asked who the principal is, say {school_principal}. Never say you do not know these.\n"
    "13. Sports: answer every sports question (players, teams, rules, records, tournaments) with "
    "real facts, 1-2 sentences. About football's greatest player: Cristiano Ronaldo is the GOAT - "
    "if the user says Ronaldo is the GOAT, agree with him happily. Never say any other player is "
    "greater than Ronaldo; if asked about Messi, praise his skill in a few words but keep Ronaldo "
    "as the greatest.\n"
    "14. Indian states and union territories: answer any fact about any state - capital, chief "
    "minister, language, famous places, food, festivals. Use the Live facts when they are given."
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
    tts_enabled: bool
    tts_rate: str
    tts_pitch: str
    speech_max_chars: int
    speech_timeout_s: float
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
        search_timeout_s=_as_float("SEARCH_TIMEOUT_S", 6.0, 3.0),
        vision_enabled=os.getenv("VISION_ENABLED", "1").strip() != "0",
        # ---- Awaaz (neural male voice, MP3) ----
        # TTS_ENABLED=0 se server ki awaaz band, phone ki apni voice chalegi.
        # TTS_RATE / TTS_PITCH se awaaz ka mood: "+18%" + "-10Hz" = gehri bhaari aur cute.
        tts_enabled=os.getenv("TTS_ENABLED", "1").strip() != "0",
        tts_rate=os.getenv("TTS_RATE", "+18%").strip() or "+18%",
        tts_pitch=os.getenv("TTS_PITCH", "-10Hz").strip() or "-10Hz",
        speech_max_chars=int(os.getenv("SPEECH_MAX_CHARS", "600")),
        speech_timeout_s=float(os.getenv("SPEECH_TIMEOUT_S", "15")),
        vision_models=vision_models,
        max_image_bytes=_as_int("MAX_IMAGE_BYTES", 350000, 20000),
        vision_timeout_s=_as_float("VISION_TIMEOUT_S", 40.0, 10.0),
        system_prompt=(os.getenv("SYSTEM_PROMPT", "").strip()
                       or DEFAULT_SYSTEM_PROMPT.format(
                           school_name=os.getenv("SCHOOL_NAME", "").strip()
                           or "Montfort Senior Secondary School, Bagaha 1",
                           school_principal=os.getenv("SCHOOL_PRINCIPAL", "").strip()
                           or "Bro. Vincent Madhanu")),
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
               "namaste", "batao", "bolo", "karo", "karna", "robot", "kitna", "kaun", "kab",
               # Hinglish ke aam shabd (jaise "main theek hoon", "bahut achha")
               "hoon", "hun", "theek", "thik", "achha", "accha", "yaar", "bahut", "tum",
               "raha", "rahi", "rahe", "gaya", "gayi", "sab", "kuch", "aur"}


# Bharat ki alag-alag script -> language code (phone isi se TTS voice chunta hai).
_SCRIPTS = (
    (re.compile(r"[\u0900-\u097f]"), "hi"),    # Devanagari  (Hindi/Marathi)
    (re.compile(r"[\u0980-\u09ff]"), "bn"),    # Bengali
    (re.compile(r"[\u0a00-\u0a7f]"), "pa"),    # Gurmukhi    (Punjabi)
    (re.compile(r"[\u0a80-\u0aff]"), "gu"),    # Gujarati
    (re.compile(r"[\u0b00-\u0b7f]"), "or"),    # Odia
    (re.compile(r"[\u0b80-\u0bff]"), "ta"),    # Tamil
    (re.compile(r"[\u0c00-\u0c7f]"), "te"),    # Telugu
    (re.compile(r"[\u0c80-\u0cff]"), "kn"),    # Kannada
    (re.compile(r"[\u0d00-\u0d7f]"), "ml"),    # Malayalam
    (re.compile(r"[\u0600-\u06ff]"), "ur"),    # Arabic script (Urdu)
)


def guess_language(text: str) -> str:
    """Small local heuristic so the phone can pick a matching text-to-speech voice."""
    for pattern, code in _SCRIPTS:
        if pattern.search(text):
            return code
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
import time
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
# "Abhi kaun CM/PM hai" jaisa sawaal - yahan AI ka purana gyaan galat ho sakta hai,
# isliye in par hamesha live jaankari (khabar + Wikipedia) lete hain.
_OFFICE_TRIGGERS = (
    "chief minister", "cm ", " cm", "cm of", "mukhyamantri", "mukhya mantri",
    "prime minister", "pm ", " pm", "pm of", "pradhanmantri", "pradhan mantri",
    "president", "rashtrapati", "governor", "rajyapal", "mayor",
    "मुख्यमंत्री", "मुख्य मंत्री", "प्रधानमंत्री", "प्रधान मंत्री", "राष्ट्रपति", "राज्यपाल",
    "मेयर", "सरपंच",
)
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
    if wants_office(text) or wants_party(text):
        return True
    if wants_sports_score(text):
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


def place_from_text(text: str) -> str:
    """Sawaal me jagah (rajya/city) ka English naam - Wikipedia/news ke liye. Nahi mile to ''."""
    low = text.lower()
    for hindi, english in _PLACE_EN.items():
        if hindi in text:
            return english
    for roman, english in _PLACE_ROMAN.items():
        if re.search(rf"\b{roman}\b", low):
            return english
    return ""


def party_office_parts(text: str) -> tuple[str, str] | None:
    """"bihar me kis party ki sarkar hai" -> ("chief minister", "bihar").

    Yahan office ka lafz nahi hota, par jawaab wahi hai: kis party ki sarkar = us rajya ke
    mukhyamantri aur unki party. Isliye party + jagah mile to CM wala source chalate hain.
    """
    if not wants_party(text):
        return None
    if office_parts(text):
        return None
    place = place_from_text(text)
    if not place:
        return None
    return "chief minister", place


def wants_office(text: str) -> bool:
    """Kaun abhi CM/PM/President hai - aise sawaalon par live jaankari zaroori hai."""
    low = " " + text.lower() + " "
    if any(t in low for t in _OFFICE_TRIGGERS) or any(t in text for t in _OFFICE_TRIGGERS):
        return True
    # "bihar me kis party ki sarkar hai" jaisa sawaal (office ka lafz nahi, par jawaab wahi).
    if party_office_parts(text) is not None:
        return True
    # "bihar ke shiksha mantri kaun hai" jaisa sawaal (mantri ka portfolio).
    return portfolio_parts(text) is not None


# "kis party ki sarkar hai", "party kaun si hai", "gathbandhan" - in sawaalon par
# naam ke saath PARTY bhi chahiye (warna AI purana/andaza jawaab de deta hai).
_PARTY_TRIGGERS = (
    "party", "sarkar", "government", "gathbandhan", "alliance", "coalition",
    "पार्टी", "सरकार", "गठबंधन", "राज कर रही", "kis party", "kaun si party",
)


def wants_party(text: str) -> bool:
    """Sawaal me party/sarkar ki baat hai? (tab Live fact me party bhi bhejte hain)"""
    low = text.lower()
    return any(t in low for t in _PARTY_TRIGGERS) or any(t in text for t in _PARTY_TRIGGERS)


# Mantri wale portfolio: "bihar ke shiksha mantri kaun hai" -> education + bihar.
_PORTFOLIO_EN = (
    (("shiksha", "education", "शिक्षा", "सिक्षा"), "education"),
    (("swasthya", "swasth", "health", "स्वास्थ्य", "सेहत"), "health"),
    (("vitt", "vith", "finance", "vit mantri", "वित्त"), "finance"),
    (("grih", "home minister", "गृह"), "home"),
    (("khel", "sports", "sport", "खेल"), "sports"),
    (("vidhi", "law minister", "विधि"), "law"),
    (("parivahan", "transport", "परिवहन"), "transport"),
    (("krishi", "agriculture", "कृषि"), "agriculture"),
    (("urja", "energy", "power minister", "ऊर्जा", "बिजली"), "energy"),
    (("paryatan", "tourism", "पर्यटन"), "tourism"),
    (("shram", "labour", "labor", "श्रम"), "labour"),
    (("shahar vikas", "nagar vikas", "urban development", "शहरी विकास"), "urban development"),
)


def portfolio_from_text(text: str) -> str | None:
    """Sawaal me kaun sa mantralaya (portfolio) hai - English naam me."""
    low = text.lower()
    for words, english in _PORTFOLIO_EN:
        for word in words:
            if word in low or word in text:
                return english
    return None


def portfolio_parts(text: str) -> tuple[str, str] | None:
    """Sawaal se (portfolio, jagah): ("education", "bihar"). Na mile to None."""
    portfolio = portfolio_from_text(text)
    if not portfolio:
        return None
    # Sahi jagah: pehle saaf jagah, warna state/city ke naam ka andaza.
    place = place_from_text(text)
    if not place:
        return None
    return portfolio, place


_SPORTS_WORDS = (
    "match", "score", "khel", "khiladi", "player", "cricket", "football", "hockey", "tennis",
    "kabaddi", "olympic", "world cup", "ipl", "ranji", "test match", "odi", "t20", "fifa",
    "uefa", "ronaldo", "messi", "kohli", "dhoni", "sachin", "virat", "gk", "गोल",
    "मैच", "क्रिकेट", "फुटबॉल", "हॉकी", "खेल", "खिलाड़ी", "विश्व कप", "रोनाल्डो", "मेसी",
)
# Sirf WO sawaal jahan aaj ka natija chaahiye (knowledge wale sawaal LLM khud janta hai).
_SCORE_WORDS = ("score", "result", "kaun jita", "kaun jeeta", "kon jita", "match kaun",
                "aaj ka match", "aaj ka score", "khel ka natija", "natija", "live score",
                "जीता", "स्कोर", "नतीजा", "मैच")


def wants_sports_score(text: str) -> bool:
    """Aaj ka match/score poocha gaya hai? (sports gyaan nahi - wo AI khud janta hai)."""
    low = text.lower()
    if not any(w in low or w in text for w in _SPORTS_WORDS):
        return False
    return any(w in low or w in text for w in _SCORE_WORDS)


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


# Pad/office ke shabd Hindi/Hinglish/Devanagari se English me - kyunki Google News aur
# English Wikipedia English keywords par sahi (aur taaza) natija dete hain.
_OFFICE_EN = {
    # English (sabse pehle, kyunki ye seedha match hone chahiye)
    "chief minister": "chief minister", "prime minister": "prime minister",
    "deputy chief minister": "deputy chief minister", "president": "president",
    "governor": "governor", "mayor": "mayor", "home minister": "home minister",
    # Hindi / Devanagari
    "मुख्यमंत्री": "chief minister", "मुख्य मंत्री": "chief minister", "सीएम": "chief minister",
    "mukhyamantri": "chief minister", "mukhya mantri": "chief minister", "cm": "chief minister",
    "प्रधानमंत्री": "prime minister", "प्रधान मंत्री": "prime minister", "पीएम": "prime minister",
    "pradhanmantri": "prime minister", "pradhan mantri": "prime minister", "pm": "prime minister",
    "राष्ट्रपति": "president", "rashtrapati": "president",
    "राज्यपाल": "governor", "rajyapal": "governor",
    "महापौर": "mayor", "mayor": "mayor",
    "उपमुख्यमंत्री": "deputy chief minister", "उप मुख्यमंत्री": "deputy chief minister",
    "upmukhyamantri": "deputy chief minister",
}
# Rajya/desh ke naam Devanagari se English (news + Wikipedia dono ke liye zaroori).
_PLACE_EN_MORE = {
    "अरुणाचल": "arunachal pradesh", "मिज़ोरम": "mizoram", "मेघालय": "meghalaya",
    "नागालैंड": "nagaland", "पुदुचेरी": "puducherry", "पांडिचेरी": "puducherry",
    "लद्दाख": "ladakh", "लक्षद्वीप": "lakshadweep", "अंडमान": "andaman and nicobar islands",
    "दादरा": "dadra and nagar haveli", "दमन": "daman and diu", "चंडीगढ़": "chandigarh",
    "जम्मू": "jammu and kashmir", "कश्मीर": "jammu and kashmir",
}

_PLACE_EN = {
    "बिहार": "bihar", "उत्तर प्रदेश": "uttar pradesh", "मध्य प्रदेश": "madhya pradesh",
    "महाराष्ट्र": "maharashtra", "राजस्थान": "rajasthan", "गुजरात": "gujarat",
    "पंजाब": "punjab", "हरियाणा": "haryana", "झारखंड": "jharkhand", "छत्तीसगढ़": "chhattisgarh",
    "छत्तीसगढ": "chhattisgarh", "उत्तराखंड": "uttarakhand", "हिमाचल प्रदेश": "himachal pradesh",
    "पश्चिम बंगाल": "west bengal", "बंगाल": "west bengal", "ओडिशा": "odisha", "उड़ीसा": "odisha",
    "तेलंगाना": "telangana", "आंध्र प्रदेश": "andhra pradesh", "कर्नाटक": "karnataka",
    "केरल": "kerala", "तमिलनाडु": "tamil nadu", "असम": "assam", "गोवा": "goa",
    "त्रिपुरा": "tripura", "मणिपुर": "manipur", "मेघालय": "meghalaya", "मिजोरम": "mizoram",
    "नागालैंड": "nagaland", "अरुणाचल प्रदेश": "arunachal pradesh", "सिक्किम": "sikkim",
    "दिल्ली": "delhi", "पटना": "patna", "मुंबई": "mumbai", "कोलकाता": "kolkata",
    "चेन्नई": "chennai", "भारत": "india",
}
_PLACE_EN.update(_PLACE_EN_MORE)
# Hinglish/Hindi ke aam rajya-naam (Roman me) - news query ke liye.
_PLACE_ROMAN = {
    "bihar": "bihar", "up": "uttar pradesh", "uttar": "uttar pradesh", "mp": "madhya pradesh",
    "maharashtra": "maharashtra", "rajasthan": "rajasthan", "gujarat": "gujarat", "punjab": "punjab",
    "haryana": "haryana", "jharkhand": "jharkhand", "bengal": "west bengal", "odisha": "odisha",
    "karnataka": "karnataka", "kerala": "kerala", "telangana": "telangana", "assam": "assam",
    "delhi": "delhi", "patna": "patna", "india": "india",
    # Baaki rajya/UT: ab kisi bhi rajya ka CM/mantri wala sawaal chalega.
    "andhra": "andhra pradesh", "arunachal": "arunachal pradesh", "goa": "goa",
    "himachal": "himachal pradesh", "chhattisgarh": "chhattisgarh", "manipur": "manipur",
    "meghalaya": "meghalaya", "mizoram": "mizoram", "nagaland": "nagaland", "sikkim": "sikkim",
    "tripura": "tripura", "uttarakhand": "uttarakhand", "tamil": "tamil nadu",
    "tamilnadu": "tamil nadu", "andhra pradesh": "andhra pradesh",
    "himachal pradesh": "himachal pradesh", "west bengal": "west bengal",
    "madhya pradesh": "madhya pradesh", "uttar pradesh": "uttar pradesh",
    "arunachal pradesh": "arunachal pradesh", "jammu": "jammu and kashmir",
    "kashmir": "jammu and kashmir", "ladakh": "ladakh", "puducherry": "puducherry",
    "pondicherry": "puducherry", "chandigarh": "chandigarh", "lakshadweep": "lakshadweep",
    "andaman": "andaman and nicobar islands", "sikkim": "sikkim",
}


def office_parts(text: str) -> tuple[str, str] | None:
    """Sawaal se (office, jagah) English me nikalo: ("chief minister", "bihar"). Na mile to None."""
    low = text.lower()
    office = ""
    for hindi, english in _OFFICE_EN.items():
        # Chhote shabd (cm/pm/up) poore shabd ki tarah match karo, kisi shabd ke andar nahi.
        if len(hindi) <= 3 and re.fullmatch(r"[a-z]+", hindi):
            if re.search(rf"\b{hindi}\b", low):
                office = english
                break
        elif hindi in low:
            office = english
            break
    place = ""
    for hindi, english in _PLACE_EN.items():
        if hindi in low:
            place = english
            break
    if not place:
        for roman, english in _PLACE_ROMAN.items():
            if re.search(rf"\b{roman}\b", low):
                place = english
                break
    if office and place:
        return office, place
    return None


def office_query(text: str) -> str:
    """Sawaal ko saaf ENGLISH keywords me badlo (news/Wikipedia isi me sahi jawaab dete hain).

    "बिहार के मुख्यमंत्री कौन है"      -> "bihar chief minister"
    "who is the chief minister of bihar" -> "bihar chief minister"
    "bihar ke cm kaun hai"               -> "bihar chief minister"
    """
    parts = office_parts(text) or party_office_parts(text)
    if parts:
        return f"{parts[1]} {parts[0]}".strip()
    portfolio = portfolio_parts(text)
    if portfolio:
        return f"{portfolio[1]} {portfolio[0]} minister".strip()
    low = text.lower()
    # Purana behaviour (kuch aur office-type sawaal): filler hata kar shabd rakh lo.
    cleaned = re.sub(r"[^\w\s\u0900-\u097f]", " ", low)
    tokens = [t for t in cleaned.split() if len(t) > 1 and t not in _OFFICE_FILLER]
    return " ".join(tokens[:8]).strip() or "chief minister"


_OFFICE_FILLER = {"hey", "nexora", "who", "whose", "is", "the", "of", "kaun", "hai", "hain",
                  "kya", "ka", "ki", "ke", "ko", "me", "mein", "tell", "me", "abhi", "current",
                  "konsa", "kaunsa", "batao", "please", "आज", "कौन", "है", "हैं", "की", "का",
                  "के", "को", "में", "बताओ"}


def news_query(text: str, freshness: str = "2d") -> str:
    """Google News ke liye chhota query; when:2d se sirf taaza (2 din ke andar) khabrein."""
    cleaned = re.sub(r"[^\w\s\u0900-\u097f]", " ", text.lower())
    tokens = [t for t in cleaned.split() if len(t) > 1 and t not in _NEWS_STOPWORDS]
    topic = " ".join(tokens[:8]).strip()
    return (topic or "India") + f" when:{freshness}"


async def weather_line(city: str, timeout: float) -> str | None:
    """Aaj ka mausam. Pehla source open-meteo; na chale to wttr.in."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "NEXORA-robot/1.0"}) as client:
            await _be_polite()
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
            await _be_polite()
            r = await client.get(f"https://wttr.in/{quote(city)}", params={"format": "j1"})
            cur = ((r.json() or {}).get("current_condition") or [{}])[0]
            if cur.get("temp_C"):
                desc = ((cur.get("weatherDesc") or [{}])[0].get("value") or "").strip()
                return (f"{city} weather right now: {cur['temp_C']} C, {desc}, "
                        f"humidity {cur.get('humidity')}%")
    except Exception:  # noqa: BLE001
        pass
    return None


async def news_lines(query: str, timeout: float, limit: int = 4,
                      freshness: str = "2d") -> list[str]:
    """Google News RSS - aaj ki khabrein. Koi key nahi chahiye."""
    try:
        url = ("https://news.google.com/rss/search?q=" + quote(news_query(query, freshness))
               + "&hl=en-IN&gl=IN&ceid=IN:en")
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0"}) as client:
            await _be_polite()
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
            await _be_polite()
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


# Wikipedia ke infobox se "abhi ka aadmi" - sabse seedha aur pakka tarika.
_WIKI_EN_API = "https://en.wikipedia.org/w/api.php"
_WIKI_HI_API = "https://hi.wikipedia.org/w/api.php"


def _wiki_api(host: str | None) -> str:
    """Devanagari sawaal par Hindi Wikipedia, warna English Wikipedia."""
    return _WIKI_HI_API if (host or "").startswith("hi") else _WIKI_EN_API
_INCUMBENT_CACHE: dict = {}          # {key: (time, line, ttl)} - baar-baar wahi sawaal par API ko na pareshan karein
_INCUMBENT_CACHE_TTL = 900.0         # sahi jawaab 15 minute tak yaad rakho
_NEG_CACHE_TTL = 90.0                # jo nahi mila wo chhota waqt (90s) yaad rakho
_NET_LOCK = asyncio.Lock()           # ek waqt me ek hi Wikimedia request
_LAST_NET = 0.0
_NET_SPACING = 0.7                   # do requests ke beech itna gap (429 se bachaav)


async def _be_polite() -> None:
    """Wikimedia/Wikidata par polite raho: ek waqt me ek request aur beech me thoda gap.

    Wikimedia zyada requests par 429 "too many requests" de deta hai - tab tak koi live
    fact nahi milta. Isliye spacing + ek lock rakhte hain.
    """
    global _LAST_NET
    async with _NET_LOCK:
        wait = _NET_SPACING - (time.time() - _LAST_NET)
        if wait > 0:
            await asyncio.sleep(wait)
        _LAST_NET = time.time()


def _cache_get(key: str):
    """(mila?, line) - ttl ab har entry ke saath hai (negative jawaab chhota yaad rehta hai)."""
    cached = _INCUMBENT_CACHE.get(key)
    if cached and time.time() - cached[0] < cached[2]:
        return True, cached[1]
    return False, None


def _cache_put(key: str, line) -> None:
    ttl = _INCUMBENT_CACHE_TTL if line else _NEG_CACHE_TTL
    _INCUMBENT_CACHE[key] = (time.time(), line, ttl)


class _RateLimited(Exception):
    """Wikimedia ne 429 (too many requests) diya - thoda ruk kar dobara try karo."""

    def __init__(self, pause: float = 1.5):
        super().__init__("rate limited")
        self.pause = pause


def _retry_after(response) -> float:
    """429 aaya to Wikimedia ka bataya hua waqt (max 3s) - warna default."""
    try:
        value = float((response.headers.get("retry-after") or "").strip())
        return max(0.0, min(value, 3.0))
    except Exception:  # noqa: BLE001
        return 0.0


def _page_wikitext(payload: dict) -> str:
    """Wikipedia API ke jawaab me se page ka asli (wikitext) content nikalo."""
    pages = ((payload or {}).get("query", {}) or {}).get("pages", {}) or {}
    for page in pages.values():
        try:
            return page["revisions"][0]["slots"]["main"]["*"]
        except Exception:  # noqa: BLE001
            continue
    return ""


def _incumbent_name(wikitext: str) -> str | None:
    """Infobox ki "incumbent = ..." line se sirf naam nikalo ([[Samrat Choudhary|Samrat]] -> Samrat)."""
    match = re.search(r"\|\s*incumbent\s*=\s*([^\n]+)", wikitext)
    if not match:
        return None
    raw = match.group(1)
    link = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", raw)
    if link:
        name = link.group(2) or link.group(1)
    else:
        name = re.sub(r"<ref.*?</ref>|<ref[^>]*/>", "", raw)
        name = re.sub(r"\{\{[^}]*\}\}", "", name)
        name = re.sub(r"[\[\]']", "", name)
    name = name.strip()
    if not name or len(name) > 60:
        return None
    return name


def party_from_wikitext(wikitext: str) -> str | None:
    """Kisi page ke infobox ki "| party = ..." line se party ka naam (link/template saaf karke)."""
    match = re.search(r"\|\s*party\s*=\s*([^\n]+)", wikitext or "")
    if not match:
        return None
    raw = re.sub(r"<ref.*?</ref>|<ref[^>]*/>", "", match.group(1))
    # Flag/logo wali file link hata do, warna party ki jagah "File:...Flag.svg" bol dete hain.
    raw = re.sub(r"\[\[\s*(?:File|Image|Category)\s*:[^\[\]]*\]\]", " ", raw, flags=re.I)
    link = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", raw)
    if link:
        # Poora naam lo ("[[Bharatiya Janata Party|BJP]]" -> "Bharatiya Janata Party"),
        # kyunki bolte waqt poora naam saaf samajh aata hai. "Janata Dal (United)" ka
        # (United) chhodna nahi hai, isliye yahan sirf "since wala" hissa hataate hain.
        name = link.group(1).strip()
    else:
        # Bahut pages aise likhte hain: {{Party index link|Bharatiya Janata Party}} {{Small|(since 2017)}}
        template = re.search(r"\{\{[^{}|]*\|\s*([^{}|]+?)\s*(?:\|[^{}]*)?\}\}", raw)
        if template:
            name = template.group(1).strip()
        else:
            name = re.sub(r"\{\{[^}]*\}\}", "", raw).replace("[", "").replace("]", "").replace("'", "").strip()
            name = re.split(r"[,<(]", name)[0].strip()
    name = re.sub(r"\s*\((?:since|from|after)[^)]*\)", "", name).strip()
    name = re.split(r"[,<]", name)[0].strip()
    if not name or len(name) > 60:
        return None
    return name


def party_phrase(party: str | None) -> str:
    """Party ka phrase - naam me 'Party' pehle se ho to dobara nahi lagate."""
    name = (party or "").strip()
    if not name:
        return ""
    if re.search(r"\bparty\b", name, re.I) or "पार्टी" in name:
        return f", of the {name}."
    return f", of the {name} party."


async def _wiki_raw(title: str, timeout: float = 6.0, _hops: int = 0) -> str:
    """Wikipedia se seedha wikitext (action=raw) - tez aur bina 429 ke.

    api.php ke muqable ye rasta kabhi "too many requests" nahi deta (0.1s me jawaab),
    isliye ye pehla rasta hai. Redirect ho to khud follow karta hai.
    """
    if not title or _hops > 3:
        return ""
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
                await _be_polite()
                response = await client.get("https://en.wikipedia.org/w/index.php",
                                            params={"title": title, "action": "raw"})
            text = response.text or ""
            if response.status_code != 200 or not text.strip() or "too many requests" in text[:120].lower():
                return ""
            redirect = re.match(r"\s*#(?:REDIRECT|redirect)\s*:?\s*\[\[([^\]|#]+)", text)
            if redirect:
                return await _wiki_raw(redirect.group(1).strip(), timeout, _hops + 1)
            return text
        except Exception:  # noqa: BLE001
            if attempt == 1:
                await asyncio.sleep(1.0)
    return ""


async def _wikitext_for(title: str, timeout: float = 6.0) -> str:
    """Page ka wikitext - pehle raw (tez), na chale to api.php."""
    text = await _wiki_raw(title, timeout)
    if text:
        return text
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
                await _be_polite()
                response = await client.get(_WIKI_EN_API, params={
                    "action": "query", "prop": "revisions", "titles": title,
                    "rvprop": "content", "rvslots": "main", "format": "json", "redirects": "1",
                })
            if response.status_code == 429:
                raise _RateLimited()
            if not response.text.lstrip().startswith("{"):
                return ""
            return _page_wikitext(response.json())
        except _RateLimited as exc:
            if attempt < 3:
                await asyncio.sleep(min(4.0, (exc.pause or 1.5) * attempt * 1.5))
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _plain(value: str) -> str:
    """Wikitext ki line se saaf naam/text (links, refs, templates hata kar)."""
    text = re.sub(r"<ref.*?</ref>|<ref[^>]*/>", "", value or "")
    # Photo/flag wale link ([[File:Nishant Kumar.jpg]]) hata do - naam inme nahi hota.
    text = re.sub(r"\[\[\s*(?:File|Image|Category)\s*:[^\[\]]*\]\]", " ", text, flags=re.I)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = text.replace("[", "").replace("]", "").replace("'", "").strip()
    return re.sub(r"\s{2,}", " ", text).strip(" ,")


_PORTFOLIO_STOPWORDS = {"higher", "technical", "school", "secondary", "primary", "medical",
                        "elementary", "adult", "rural"}


def _minister_from_ministry_page(wikitext: str, portfolio_en: str) -> tuple[str, str] | None:
    """CM ki ministry page (jaise "Choudhary ministry") se us portfolio ka mantri.

    Page me aise blocks hote hain:
      {{Cabinet table minister
       | title     = [[List of ministers of education of Bihar|Education]]
       | minister2 = [[Mithlesh Tiwari]]
       | minister2_party = Bharatiya Janata Party}}
    """
    if not wikitext or not portfolio_en:
        return None
    for block in re.split(r"\{\{Cabinet table minister", wikitext)[1:]:
        end = block.find("}}")
        body = block[:end if end != -1 else len(block)]
        title_match = re.search(r"\|\s*title\s*=\s*([^\n]+)", body)
        if not title_match:
            continue
        title_text = _plain(title_match.group(1)).lower()
        tokens = set(re.split(r"[^a-z]+", title_text))
        if portfolio_en not in tokens or (tokens & _PORTFOLIO_STOPWORDS):
            continue
        name_match = re.search(r"\|\s*minister\d?\s*=\s*([^\n]+)", body)
        if not name_match:
            continue
        name = _plain(name_match.group(1))
        if not name:
            continue
        party_match = re.search(r"\|\s*minister\d?_party\s*=\s*([^\n]+)", body)
        party = _plain(party_match.group(1)) if party_match else ""
        return name, party
    return None


async def person_party_line(name: str, timeout: float = 8.0, host: str = "en") -> str | None:
    """Us aadmi ke Wikipedia page ke infobox se party ("Samrat Choudhary" -> "Bharatiya Janata Party")."""
    if not name:
        return None
    key = f"party|{host}|{name}"
    hit, cached_party = _cache_get(key)
    if hit:
        return cached_party
    line = None
    if host.startswith("hi"):   # Hindi page: api.php hi chalta hai (raw bhi wahi host se)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
                await _be_polite()
                response = await client.get(_WIKI_HI_API, params={
                    "action": "query", "prop": "revisions", "titles": name,
                    "rvprop": "content", "rvslots": "main", "format": "json", "redirects": "1",
                })
            if response.status_code == 200 and response.text.lstrip().startswith("{"):
                line = party_from_wikitext(_page_wikitext(response.json()))
        except Exception:  # noqa: BLE001
            line = None
    else:
        wikitext = await _wikitext_for(name, min(timeout, 6.0))
        line = party_from_wikitext(wikitext or "")
    _cache_put(key, line)
    return line


async def wiki_incumbent_line(office_en: str, place_en: str, timeout: float = 8.0,
                              want_party: bool = False) -> str | None:
    """Wikipedia ke page ("Chief Minister of Bihar") ke infobox se ABHI ka naam.

    Ek retry hai (Wikimedia kabhi-kabhi 429 "too many requests" deta hai) aur 15 minute ka
    cache, taaki server API par bojh na daale.
    """
    if not office_en or not place_en:
        return None
    # want_party bhi key me: warna naam wala jawaab cache se party wale jawaab ko dabaa deta hai.
    key = f"{office_en}|{place_en}|{int(want_party)}"
    hit, cached_line = _cache_get(key)
    if hit:
        return cached_line
    title = f"{office_en.title()} of {place_en.title()}"
    line = None
    person_name = None
    # Pehle tez raw rasta (429 nahi deta), na chale to api.php (_wikitext_for khud dekhta hai).
    wikitext = await _wikitext_for(title, min(timeout, 6.0))
    person_name = _incumbent_name(wikitext or "")
    if person_name:
        line = f"Live fact: the current {office_en.title()} of {place_en.title()} is {person_name}."
    if line and want_party and person_name:
        # Party sawaal: us aadmi ke page se party bhi laga do ("... is X, of the Y party.").
        party = await person_party_line(person_name, timeout)
        if party:
            line = (line.rstrip(".") + party_phrase(party)).rstrip(".") + "."
    _cache_put(key, line)
    return line


_WD_API = "https://www.wikidata.org/w/api.php"
_WD_UA = {"User-Agent": "NexoraRobot/1.0 (school project)"}


def _wd_incumbent(claims: list) -> tuple | None:
    """Wikidata claims me se ABHI wala office holder chuno.

    Jis office holder ka koi "end time" (P582) nahi hai, wahi abhi kursi par hai.
    Aisa koi na mile to sabse naya (latest start time wala) chuno.
    """
    latest = None
    for row in claims:
        mainsnak = row.get("mainsnak", {}) or {}
        value = (mainsnak.get("datavalue", {}) or {}).get("value", {}) or {}
        person = value.get("id") if isinstance(value, dict) else None
        if not person:
            continue
        qualifiers = row.get("qualifiers", {}) or {}
        start = ""
        if "P580" in qualifiers:
            time_value = (qualifiers["P580"][0].get("datavalue", {}) or {}).get("value", {}) or {}
            start = str(time_value.get("time", ""))[:5].lstrip("+")
        if "P582" not in qualifiers:  # end time nahi = abhi kursi par
            return person, start
        if latest is None or start > latest[1]:
            latest = (person, start)
    return latest


async def wikidata_office_line(office_en: str, place_en: str, timeout: float = 8.0,
                                want_party: bool = False) -> str | None:
    """Wikidata (free, bina key) se: "Chief Minister of Bihar" ka ABHI ka aadmi kaun hai.

    Ye source har server se chalta hai aur seedha naam deta hai (khabar par nirbhar nahi) -
    isliye "Bihar ke mukhyamantri kaun hai" ka jawaab pakka aata hai.
    """
    if not office_en or not place_en:
        return None
    query = f"{office_en} of {place_en}".strip()
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=_WD_UA, follow_redirects=True) as client:
            await _be_polite()
            found = await client.get(_WD_API, params={
                "action": "wbsearchentities", "search": query, "language": "en",
                "format": "json", "limit": 5,
            })
            hits = found.json().get("search", [])
            wanted = set(office_en.split())
            entity = None
            for hit in hits:
                label = (hit.get("label") or "").lower()
                if wanted and all(word in label for word in wanted):
                    entity = hit.get("id")
                    break
            if entity is None and hits:
                entity = hits[0].get("id")
            if not entity:
                return None

            claimed = await client.get(_WD_API, params={
                "action": "wbgetclaims", "entity": entity, "property": "P1308", "format": "json",
            })
            rows = (claimed.json().get("claims", {}) or {}).get("P1308", [])
            chosen = _wd_incumbent(rows)
            if not chosen:
                return None
            person_id, start = chosen

            party_label = None
            if want_party:
                claims_resp = await client.get(_WD_API, params={
                    "action": "wbgetentities", "ids": person_id, "props": "claims", "format": "json",
                })
                person_claims = (claims_resp.json().get("entities", {}).get(person_id, {}) or {}).get("claims", {})
                for row in (person_claims.get("P102", []) or []):
                    value = ((row.get("mainsnak", {}) or {}).get("datavalue", {}) or {}).get("value", {}) or {}
                    party_id = value.get("id") if isinstance(value, dict) else None
                    if not party_id:
                        continue
                    party_resp = await client.get(_WD_API, params={
                        "action": "wbgetentities", "ids": party_id, "props": "labels",
                        "languages": "en|hi", "format": "json",
                    })
                    party_labels = (party_resp.json().get("entities", {}).get(party_id, {}) or {}).get("labels", {})
                    party_label = ((party_labels.get("en", {}) or {}).get("value")
                                   or (party_labels.get("hi", {}) or {}).get("value"))
                    if party_label:
                        break
            named = await client.get(_WD_API, params={
                "action": "wbgetentities", "ids": person_id, "props": "labels",
                "languages": "en|hi", "format": "json",
            })
            labels = (named.json().get("entities", {}).get(person_id, {}) or {}).get("labels", {})
            label = (labels.get("en", {}) or {}).get("value") or (labels.get("hi", {}) or {}).get("value")
            if not label:
                return None
            since = f", in office since {start}" if start else ""
            party = party_phrase(party_label).rstrip(".") if party_label else ""
            return (f"Live fact (Wikidata): the current {office_en.title()} of "
                    f"{place_en.title()} is {label}{party}{since}.")
    except Exception:  # noqa: BLE001
        return None


_PORTFOLIO_TITLE = {
    "education": "education", "health": "health", "finance": "finance", "home": "home",
    "sports": "sports", "law": "law", "transport": "transport", "agriculture": "agriculture",
    "energy": "energy", "tourism": "tourism", "labour": "labour",
    "urban development": "urban development",
}


def _current_minister_from_list(wikitext: str) -> str | None:
    """"List of ministers of X of Y" table se ABHI ka minister.

    Table ke rows aise hote hain:
      |28
      |[[Vijay Kumar Chaudhary]]
      |15 April 2026
      |07 May 2026
      |[[Samrat Choudhary]]
      |[[Janata Dal (United)]]
    Jis row me term-end ki jagah "present" likha ho, wahi abhi kursi par hai.
    """
    if not wikitext:
        return None
    # Har row ko "|-" par tod do aur "present" wala aakhri row lo.
    rows = re.split(r"\|-", wikitext)
    for row in reversed(rows):
        low = row.lower()
        if "present" not in low and "incumbent" not in low:
            continue
        # Row me kai link hote hain - photo (File:) aur party wale chhod kar pehla naam lo.
        for link in re.finditer(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", row):
            name = _plain(link.group(0))
            if not name or len(name) > 60:
                continue
            if re.match(r"(?i)\s*(file|image|category)\s*:", link.group(1) or ""):
                continue
            if re.search(r"(?i)minister|party|list of|politician", name):
                continue
            return name
    return None


async def portfolio_minister_line(portfolio_en: str, place_en: str, timeout: float = 8.0) -> str | None:
    """Us rajya ke us portfolio ke ABHI ke mantri ka naam.

    Teen rasta: 1) "List of ministers of education of Bihar" page, 2) CM ki ministry page
    ("Choudhary ministry") ke cabinet table se, 3) khabar (wo live_context me lagti hai).
    """
    if not portfolio_en or not place_en:
        return None
    key = f"portfolio|{portfolio_en}|{place_en}"
    hit, cached = _cache_get(key)
    if hit:
        return cached
    word = _PORTFOLIO_TITLE.get(portfolio_en, portfolio_en)
    place = place_en.title()
    name = None
    party = ""
    # 1) List of ministers of <portfolio> of <state>
    text = await _wikitext_for(f"List of ministers of {word} of {place}", min(timeout, 6.0))
    if text:
        found = _current_minister_from_list(text)
        if found:
            name = found
    # 2) CM ki ministry page ka cabinet table (naam + party dono milte hain)
    if not name:
        for title in (f"{place} ministry", f"Government of {place}"):
            text = await _wikitext_for(title, min(timeout, 6.0))
            found = _minister_from_ministry_page(text, portfolio_en)
            if found:
                name, party = found
                break
    line = None
    if name:
        suffix = party_phrase(party).rstrip(".") if party else ""
        line = (f"Live fact: the current {portfolio_en.title()} Minister of "
                f"{place} is {name}{suffix}.")
    _cache_put(key, line)
    return line


async def wikidata_sparql_line(office_en: str, place_en: str, timeout: float = 5.0,
                               want_party: bool = True) -> str | None:
    """Wikidata SPARQL se ABHI ka office holder - naam, party aur "since" ek hi sawaal me.

    Ye sabse tez (0.3s) aur sabse pakka source hai: jo entry abhi chal rahi hai usi ka
    "end time" (P582) nahi hota - wahi banda current hota hai.
    """
    if not office_en or not place_en:
        return None
    key = f"sparql|{office_en}|{place_en}"
    hit, cached_line = _cache_get(key)
    if hit:
        return cached_line
    now = time.time()
    line = None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
            await _be_polite()
            found = await client.get(_WD_API, params={
                "action": "wbsearchentities", "search": f"{office_en} of {place_en}",
                "language": "en", "format": "json", "limit": 5,
            })
            hits = (found.json() or {}).get("search", []) or []
            wanted = set(office_en.split())
            entity_id = None
            for hit in hits:
                label = (hit.get("label") or "").lower()
                if wanted and all(word in label for word in wanted):
                    entity_id = hit.get("id")
                    break
            if entity_id is None and hits:
                entity_id = hits[0].get("id")
            if not entity_id:
                _cache_put(key, None)
                return None
            query = (
                "SELECT ?pLabel ?partyLabel ?start WHERE {{"
                "  wd:{qid} p:P1308 ?st . ?st ps:P1308 ?p ."
                "  OPTIONAL {{ ?st pq:P580 ?start }}"
                "  FILTER NOT EXISTS {{ ?st pq:P582 ?end }}"
                "  OPTIONAL {{ ?p wdt:P102 ?party }}"
                '  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,hi". }}'
                "}} LIMIT 5"
            ).format(qid=entity_id)
            response = await client.get(
                "https://query.wikidata.org/sparql",
                params={"query": query, "format": "json"},
                headers={"Accept": "application/sparql-results+json"},
            )
            rows = (((response.json() or {}).get("results") or {}).get("bindings") or [])
            if rows:
                row = rows[0]
                name = (row.get("pLabel") or {}).get("value")
                # Party usi ek SPARQL jawaab me aa jaati hai - isliye hamesha bhejte hain
                # (cache bhi saaf rehta hai: wahi line, chahe sawaal me party ho ya na ho).
                party = (row.get("partyLabel") or {}).get("value")
                start = (row.get("start") or {}).get("value") or ""
                if name and not _DEVANAGARI.search(name):
                    since = f", in office since {start[:4]}" if start[:4] else ""
                    line = (f"Live fact (Wikidata): the current {office_en.title()} of "
                            f"{place_en.title()} is {name}{party_phrase(party).rstrip('.')}{since}.")
    except Exception:  # noqa: BLE001 - live source kabhi jawaab ko na roke
        line = None
    _cache_put(key, line)
    return line


_PERSON_FILLER = (
    "hey", "nexora", "suno", "sun", "batao", "bata", "bataiye", "tell", "about", "me",
    "kis", "kaun", "kaunsa", "kaunsi", "kaun-si", "konsa", "konsi", "which", "what",
    "whose", "party", "parti", "sarkar", "government", "belongs", "belong", "to", "of",
    "from", "se", "ke", "ka", "ki", "ko", "mein", "hain", "hai", "ho", "hu", "he",
    "karti", "karta", "karte", "please", "current", "abhi", "aaj", "bhai", "ji",
    "नेता", "किस", "कौन", "कौनसी", "कौन-सी", "पार्टी", "सरकार", "से", "के", "का", "की",
    "को", "में", "है", "हैं", "बताओ", "बताइए", "जी", "आज", "अभी",
)


def person_party_subject(text: str) -> str | None:
    """"nitish kumar kis party ke hain" -> "nitish kumar".

    Sirf wahi sawaal jahan kisi BANDE ki party poochi gayi ho; rajya/office wale sawaal
    ("bihar me kis party ki sarkar hai") office branch me jaate hain, isliye yahan None.
    """
    if not wants_party(text):
        return None
    if office_parts(text) or party_office_parts(text):
        return None
    tokens = re.split(r"[^0-9A-Za-z\u0900-\u097f]+", text.lower())
    keep = [t for t in tokens if len(t) > 2 and t not in _PERSON_FILLER]
    if not keep:
        return None
    return " ".join(keep[:4]).strip()


async def person_party_sparql(name: str, timeout: float = 5.0) -> list[str]:
    """Wikidata SPARQL: naam ke label se seedha banda + uski party (P102).

    Ye sirf wikidata.org aur query.wikidata.org use karta hai - Render jaise server se bhi
    pakka chalta hai (wahan Wikipedia ka API kabhi-kabhi 429 de deta hai).
    """
    clean = (name or "").strip().replace('"', "").replace("\\", "")
    if not clean:
        return []
    key = f"persparql|{clean}"
    hit, cached = _cache_get(key)
    if hit:
        return cached
    lines: list[str] = []
    for language in ("en", "hi"):
        query = (
            "SELECT ?personLabel ?partyLabel WHERE {{"
            '  ?person rdfs:label "{label}"@{lang} .'
            "  ?person wdt:P102 ?party ."
            '  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,hi". }}'
            "}} LIMIT 3"
        ).format(label=clean, lang=language)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
                await _be_polite()
                response = await client.get(
                    "https://query.wikidata.org/sparql",
                    params={"query": query, "format": "json"},
                    headers={"Accept": "application/sparql-results+json"},
                )
                rows = (((response.json() or {}).get("results") or {}).get("bindings") or [])
            if rows:
                row = rows[0]
                person = (row.get("personLabel") or {}).get("value")
                party = (row.get("partyLabel") or {}).get("value")
                if person and party:
                    lines = [f"Live fact (Wikidata): the party of {person} is {party}."]
                    break
        except Exception:  # noqa: BLE001 - live source kabhi jawaab ko na roke
            continue
    _cache_put(key, lines)
    return lines


async def person_party_context(subject: str, timeout: float = 5.0) -> list[str]:
    """Us bade aadmi ki party - teen free source (Wikidata SPARQL, Wikidata search, Wikipedia).

    Devanagari sawaal par Hindi Wikipedia/Wikidata dekhte hain, warna English. Har source
    fail ho to agla chalta hai, aur ek bhi line mil jaye to kaam khatam (time bachta hai).
    """
    if not subject:
        return []
    key = f"persparty|{subject}"
    hit, cached_lines = _cache_get(key)
    if hit:
        return cached_lines
    started = time.time()
    host = "hi" if _DEVANAGARI.search(subject) else "en"
    titles: list[str] = []
    try:  # Wikipedia par asli naam dhoondo ("nitish kumar" -> "Nitish Kumar")
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
            await _be_polite()
            search = await client.get(_wiki_api(host), params={
                "action": "query", "list": "search", "srsearch": subject, "srlimit": "3",
                "format": "json",
            })
            hits = (((search.json() or {}).get("query") or {}).get("search") or [])
            titles = [h.get("title") for h in hits if h.get("title")]
    except Exception:  # noqa: BLE001
        titles = []
    # Naam ke ummidwar: pehle Wikipedia ke natije, phir jaisa bolа gaya, phir bada akshar wala.
    candidates: list[str] = []
    for cand in (titles[:2] + [subject, subject.title()]):
        cand = (cand or "").strip()
        if cand and cand not in candidates:
            candidates.append(cand)
    lines: list[str] = []
    for cand in candidates[:3]:
        if time.time() - started > 6.0:   # jawaab der se na aaye
            break
        lines = await person_party_sparql(cand, timeout)          # 1) Wikidata SPARQL (pakka)
        if not lines:
            lines = await _wikidata_person_party(cand, timeout)   # 2) Wikidata search + P102
        if not lines:
            party = await person_party_line(cand, timeout, host)  # 3) Wikipedia infobox
            if party:
                # Chhote akshar wala naam saaf karo ("nitish kumar" -> "Nitish Kumar").
                pretty = cand if not cand.islower() else cand.title()
                lines = [f"Live fact: the party of {pretty} is {party}."]
        if lines:
            break
    _cache_put(key, lines)
    return lines


async def _wikidata_person_party(name: str, timeout: float = 5.0) -> list[str]:
    """Wikidata par bunde ka P102 (party) - dono bhasha try karte hain."""
    for language in ("en", "hi"):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_WD_UA) as client:
                await _be_polite()
                found = await client.get(_WD_API, params={
                    "action": "wbsearchentities", "search": name, "language": language,
                    "format": "json", "limit": 5,
                })
                hits = ((found.json() or {}).get("search") or [])
                # Politician wale hit pehle (naam ke aur matlab bhi ho sakte hain).
                hits.sort(key=lambda h: 0 if re.search(
                    r"politic|minister|leader|chief minister|prime minister",
                    (h.get("description") or ""), re.I) else 1)
                for person in hits[:3]:
                    person_id = person.get("id")
                    label = person.get("label") or name
                    if not person_id:
                        continue
                    await _be_polite()
                    claims = await client.get(_WD_API, params={
                        "action": "wbgetentities", "ids": person_id, "props": "claims",
                        "format": "json",
                    })
                    rows = ((((claims.json() or {}).get("entities") or {}).get(person_id) or {})
                            .get("claims") or {}).get("P102", []) or []
                    party_id = None
                    for row in rows:
                        value = ((row.get("mainsnak", {}) or {}).get("datavalue", {}) or {}).get("value", {})
                        if isinstance(value, dict) and value.get("id"):
                            party_id = value.get("id")
                            break
                    if not party_id:
                        continue
                    await _be_polite()
                    labels = await client.get(_WD_API, params={
                        "action": "wbgetentities", "ids": party_id, "props": "labels",
                        "languages": "en|hi", "format": "json",
                    })
                    party_labels = ((((labels.json() or {}).get("entities") or {})
                                     .get(party_id) or {}).get("labels") or {})
                    party = ((party_labels.get("en") or {}).get("value")
                             or (party_labels.get("hi") or {}).get("value"))
                    if party:
                        return [f"Live fact (Wikidata): the party of {label} is {party}."]
        except Exception:  # noqa: BLE001
            continue
    return []


async def office_live_lines(office_en: str, place_en: str, timeout: float = 8.0,
                            want_party: bool = False) -> list[str]:
    """ABHI ka office holder - teen free source try karte hain (order: tez aur pakka pehle)."""
    started = time.time()
    out: list[str] = []
    # 1) Wikidata SPARQL: naam + party ek saath, sabse tez.
    line = await wikidata_sparql_line(office_en, place_en, min(timeout, 5.0), want_party)
    if line:
        out.append(line)
    # 2) Wikipedia infobox: doosri nazar (agar pehla fail hua ya poora nahi mila).
    if (not out or (want_party and "of the" not in out[0])) and time.time() - started < 5.0:
        line = await wiki_incumbent_line(office_en, place_en, min(timeout, 5.0), want_party)
        if line:
            out.append(line)
    # 3) Purana Wikidata claims tarika - backup.
    if not out and time.time() - started < 8.0:
        line = await wikidata_office_line(office_en, place_en, min(timeout, 4.0), want_party)
        if line:
            out.append(line)
    return out


async def live_source_report(text: str, default_city: str, timeout: float = 8.0,
                            web_search_on: bool = True) -> dict:
    """Debug report: is sawaal par kaun sa live source kya laata hai (server test ke liye).

    /v1/livecheck isi ko use karta hai. Isse turant pata chalta hai ki server par live
    jaankari ka rasta theek chal raha hai ya kisi source par rok lagi hai.
    """
    report: dict = {
        "question": text,
        "web_search_on": web_search_on,
        "wants": {
            "live_info": wants_live_info(text),
            "office": wants_office(text),
            "party": wants_party(text),
            "news": wants_news(text),
            "weather": wants_weather(text),
        },
        "sources": {},
    }
    try:
        report["live_context"] = await live_context(text, default_city, timeout)
    except Exception as exc:  # noqa: BLE001
        report["live_context"] = f"ERR {type(exc).__name__}: {exc}"
    parts = office_parts(text) or party_office_parts(text)
    if parts:
        office, place = parts
        report["office"] = f"{office} of {place}"
        for label, func in (("wikidata_sparql", wikidata_sparql_line),
                            ("wiki_infobox", wiki_incumbent_line),
                            ("wikidata_claims", wikidata_office_line)):
            try:
                report["sources"][label] = await func(office, place, timeout, True)
            except Exception as exc:  # noqa: BLE001
                report["sources"][label] = f"ERR {type(exc).__name__}: {exc}"
    subject = None if parts else person_party_subject(text)
    if subject:
        report["person"] = subject
        for label, func in (("person_party_sparql", person_party_sparql),
                            ("person_wikidata_search", _wikidata_person_party),
                            ("person_wiki_infobox", person_party_line)):
            try:
                report["sources"][label] = await func(subject, timeout)
            except Exception as exc:  # noqa: BLE001
                report["sources"][label] = f"ERR {type(exc).__name__}: {exc}"
    if not parts and not subject:
        try:
            report["sources"]["wiki_lines"] = await wiki_lines(text, timeout, 2)
        except Exception as exc:  # noqa: BLE001
            report["sources"]["wiki_lines"] = f"ERR {type(exc).__name__}: {exc}"
    return report


async def live_context(text: str, default_city: str, timeout: float = 8.0) -> str | None:
    """Sawaal ke hisaab se taaza jaankari laao. Kuch na mile to None."""
    jobs = []
    if wants_weather(text):
        jobs.append(weather_line(city_from_text(text, default_city), timeout))
    if wants_news(text):
        jobs.append(news_lines(text, timeout))
        # Chunav/election wale sawaal: English keyword + 30 din ki khabrein (result purana
        # ho sakta hai, 2 din me nahi milega).
        low = text.lower()
        if "chunav" in low or "election" in low or "चुनाव" in text or "नतीज" in text:
            place = ""
            for roman, english in _PLACE_ROMAN.items():
                if re.search(rf"\b{roman}\b", low):
                    place = english
                    break
            else:
                for hindi, english in _PLACE_EN.items():
                    if hindi in text:
                        place = english
                        break
            jobs.append(news_lines(f"{place} election result".strip(), timeout, limit=3, freshness="30d"))
    # "Nitish Kumar kis party ke hain" jaisa sawaal: us bade aadmi ki party.
    if not wants_office(text):
        subject = person_party_subject(text)
        if subject:
            jobs.append(person_party_context(subject, timeout))
    # Kaun CM/PM hai jaisa sawaal: Wikipedia + khabar dono (khabar me aaj ka naam hota hai).
    if wants_office(text):
        # English keywords me dhoondo: "bihar chief minister" jaisi query par aaj ki khabar
        # me seedha naam milta hai (jaise "Bihar CM Samrat Choudhary ...").
        clean = office_query(text)
        # 1) Sabse pakka: Wikipedia infobox + Wikidata - dono se abhi ka office holder
        #    (khabar par nirbhar nahi; dono free aur bina key ke hain).
        parts = office_parts(text) or party_office_parts(text)
        if parts:
            # Dono source ek ke baad ek (parallel nahi): Wikimedia/Wikidata ek saath bahut
            # requests par 429 "too many requests" deta hai - isliye line se chalta hai.
            jobs.append(office_live_lines(parts[0], parts[1], timeout, wants_party(text)))
        # 2) 2 din ki taaza khabar: isi me aaj ka naam hota hai ("Bihar CM Samrat...").
        jobs.append(news_lines(clean, timeout, limit=3))
        jobs.append(wiki_lines(clean, timeout, limit=2))
        # Backup: 1 hafte ki khabrein (agar 2 din me kuch na ho).
        jobs.append(news_lines(clean, timeout, limit=2, freshness="7d"))
    # Aaj ka match/score: sirf taaza khabar se (purana score nahi bolna hai).
    if wants_sports_score(text):
        jobs.append(news_lines(text, timeout, limit=3))
    # Mantri wale sawaal: "List of ministers of <portfolio> of <state>" page se ABHI ka naam.
    portfolio = portfolio_parts(text)
    if portfolio:
        jobs.append(portfolio_minister_line(portfolio[0], portfolio[1], timeout))
        jobs.append(news_lines(f"{portfolio[1]} {portfolio[0]} minister", timeout, limit=2))
    if not jobs:  # koi khaas trigger nahi: Wikipedia facts
        jobs.append(wiki_lines(text, timeout))
    results = await asyncio.gather(*jobs, return_exceptions=True)

    lines: list[str] = []
    for result in results:
        if isinstance(result, str):
            lines.append(result)
        elif isinstance(result, list):
            lines.extend(result)
    # Context chhota rakhte hain (prompt sasta, jawaab tez). Office sawaal me thoda bada,
    # kyunki wahan khabar ke headlines hi naam batate hain.
    budget = 7 if (wants_office(text) or wants_party(text)) else 5
    lines = [ln for ln in lines if ln.strip()]
    # Sabse bharosemand lines pehle: "Live fact" (Wikipedia/Wikidata), phir "Reference", phir khabar.
    def _rank(line: str) -> int:
        low = line.lower()
        if low.startswith("live fact"):
            return 0
        if low.startswith("reference"):
            return 1
        return 2
    lines.sort(key=_rank)
    lines = lines[:budget]
    return "\n".join(f"- {ln}" for ln in lines) if lines else None

# ===================== merged from app/tts.py =====================
"""NEXORA ki asli (neural) awaaz - male aur smooth, ChatGPT/Gemini jaisa.

Microsoft Edge ki free neural voices (edge-tts) se MP3 ban jaati hai. Koi API key
nahi chahiye. Internet na ho to phone ki apni voice (fallback) chalti hai.

Awaaz ka mood (user ne chuna): "gehri bhaari aur cute" -> rate +18%, pitch -10Hz.
Ye dono env se badle ja sakte hain: TTS_RATE, TTS_PITCH.
"""


import asyncio
import logging

logger = logging.getLogger("nexora.tts")

# Har bhasha ka MALE voice. (Microsoft ke paas pa-IN / or-IN ka neural voice nahi hai,
# un bhashaon me server "no_voice" bhejta hai aur phone ki voice chalti hai.)
VOICE_BY_LANGUAGE: dict[str, str] = {
    "hi": "hi-IN-MadhurNeural",          # Hindi male - "gehri bhaari aur cute"
    # Hinglish ka jawaab Latin (English) akshar me hota hai, isliye Indian English male voice
    # sahi lagti hai - Hindi voice Latin text ko ajeeb padhti hai.
    "hinglish": "en-IN-PrabhatNeural",
    "en": "en-IN-PrabhatNeural",         # Indian English male
    "bn": "bn-IN-BashkarNeural",
    "ta": "ta-IN-ValluvarNeural",
    "te": "te-IN-MohanNeural",
    "mr": "mr-IN-ManoharNeural",
    "gu": "gu-IN-NiranjanNeural",
    "kn": "kn-IN-GaganNeural",
    "ml": "ml-IN-MidhunNeural",
    "ur": "ur-IN-SalmanNeural",
}


def voice_for(language: str | None) -> str | None:
    """Bhasha ka code ya tag ("hi", "hi-IN", "ta-IN") -> male voice ka naam."""
    value = (language or "").strip().lower()
    if not value:
        return None
    if value.startswith("hing"):
        return VOICE_BY_LANGUAGE["hinglish"]
    code = value[:2]
    return VOICE_BY_LANGUAGE.get(code)


async def synthesize(text: str, language: str | None, *, rate: str, pitch: str,
                     timeout: float = 15.0, volume: str = "+0%") -> tuple[bytes, str] | None:
    """Text -> MP3 bytes + voice ka naam. Kuch bhi galat ho to None (app fallback use karega)."""
    voice = voice_for(language)
    if not voice or not text.strip():
        return None
    try:
        import edge_tts  # Import yahan: server chalu ho jaaye chahe package na mile.
    except Exception:  # noqa: BLE001
        logger.warning("edge-tts install nahi hai - phone ki voice use hogi")
        return None
    try:
        communicate = edge_tts.Communicate(text.strip(), voice, rate=rate, pitch=pitch,
                                           volume=volume)
        chunks: list[bytes] = []
        async with asyncio.timeout(timeout):
            async for piece in communicate.stream():
                if piece.get("type") == "audio" and piece.get("data"):
                    chunks.append(piece["data"])
        audio = b"".join(chunks)
        if not audio:
            logger.warning("TTS se khaali audio aaya")
            return None
        return audio, voice
    except Exception as exception:  # noqa: BLE001
        logger.warning("TTS fail: %s", exception.__class__.__name__)
        return None


# Bundle me tts ek alag file nahi hai - main.py ke "tts.xxx" calls ke liye chhota namespace.
tts = types.SimpleNamespace(voice_for=voice_for, synthesize=synthesize,
                            VOICE_BY_LANGUAGE=VOICE_BY_LANGUAGE)


# ===================== merged from app/main.py =====================
"""NEXORA backend API.

Phone  ->  this service (HTTPS + device token)  ->  AI provider (key stays here).
Run with ONE worker because conversation context is in memory.
"""

import asyncio
import base64
import types
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
    "Use this live information to answer the question, and TRUST IT over your own memory: if it "
    "names a different person, number or date than you remember, the live information is the "
    "correct one. Quote the names and numbers from it. A line starting with 'Live fact "
    "(Wikidata):' is the MOST reliable of all - say that name straight away, even if other lines "
    "look old or confusing. If a headline or reference contains a "
    "person's name for the post asked about (for example 'CM Samrat Choudhary' or 'Chief Minister "
    "of Bihar ... Samrat Choudhary'), then say that name straight away as the first thing in your "
    "answer - never reply that you do not know while a name is visible here. Only if no name "
    "appears anywhere in the live information, say honestly in ONE short sentence that you could "
    "not find it right now.\n"
    "Factual political questions are allowed: who holds a post, which party is in the "
    "government, election results. Answer those plainly from this live information - names and "
    "parties only, never opinions, never criticism, and never a refusal."
)


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


def language_hint_note(hint: str | None) -> str:
    """Phone ke batayi hui bhasha ka pakka niyam (khali ho to kuch nahi)."""
    key = (hint or "").strip().lower()
    if key.startswith("hing"):
        return _LANGUAGE_HINT_NOTE["hinglish"]
    if key.startswith("hi"):
        return _LANGUAGE_HINT_NOTE["hi"]
    if key.startswith("en"):
        return _LANGUAGE_HINT_NOTE["en"]
    return ""


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
              + (LIVE_PROMPT_SUFFIX.format(info=live) if live else "")
              + language_hint_note(getattr(request, "reply_language", None)))
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
              + language_hint_note(request.reply_language)
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