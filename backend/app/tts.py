"""NEXORA ki asli (neural) awaaz - male aur smooth, ChatGPT/Gemini jaisa.

Microsoft Edge ki free neural voices (edge-tts) se MP3 ban jaati hai. Koi API key
nahi chahiye. Internet na ho to phone ki apni voice (fallback) chalti hai.

Awaaz ka mood (user ne chuna): "gehri bhaari aur cute" -> rate +18%, pitch -10Hz.
Ye dono env se badle ja sakte hain: TTS_RATE, TTS_PITCH.
"""

from __future__ import annotations

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
