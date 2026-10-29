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
