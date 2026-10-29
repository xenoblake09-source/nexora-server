"""NEXORA backend start karne ka aasaan tareeka.

Windows par:
    python run.py

Yeh .env padhta hai aur Uvicorn ko EK worker ke saath chalata hai
(sessions RAM mein hain, isliye ek se zyada worker nahi chalana).
"""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()  # .env se keys load karo (agar file hai)

HOST = os.getenv("NEXORA_HOST", "0.0.0.0")
PORT = int(os.getenv("NEXORA_PORT", "8000"))

if __name__ == "__main__":
    provider = os.getenv("AI_PROVIDER", "gemini").strip()
    ready = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

    print("NEXORA backend shuru ho raha hai...")
    print(f"  provider : {provider}")
    print(f"  address  : http://{HOST}:{PORT}")
    print(f"  health   : http://127.0.0.1:{PORT}/health")

    if provider == "stub":
        print("  NOTE     : stub mode sirf connection test ke liye hai (AI jawab nahi).")
    elif not ready:
        print("  WARNING  : koi AI key .env mein nahi mili — /v1/chat 'not_configured' dega.")
    else:
        print("  AI key   : mil gayi ✔")

    print("  Band karne ke liye: Ctrl + C\n")

    # workers=1 zaroori hai (in-memory sessions).
    uvicorn.run("app.main:app", host=HOST, port=PORT, workers=1, log_level="info")
