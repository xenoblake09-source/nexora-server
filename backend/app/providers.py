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
