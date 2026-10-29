"""NEXORA backend configuration. Secrets only ever come from the environment (.env)."""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

# Ye version /health aur server page par dikhta hai - upload hua ya nahi, isse turant pata
# chal jaata hai (Render purana code chala raha ho to yahi number purana dikhega).
# Keep the Stage-F bundle stable so previously installed location clients keep their capability
# guard. Stage G is separately advertised in /health as school_retrieval_bundle.
BUNDLE_VERSION = "2026-10-29-stage-f-location"
SCHOOL_RETRIEVAL_BUNDLE = "2026-10-29-stage-g-school-retrieval"

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
    "12. School information requires an official public source or an explicitly authorised document. "
    "Do not invent a school name, address, principal, staff member, schedule, or student data. If "
    "no authorised source is provided, say briefly that it is not available to verify.\n"
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
        system_prompt=(os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT),
    )
