# NEXORA backend — secure AI brain (Phase 3)

Yeh chhota Python service aapke **phone** aur **AI provider** ke beech baithta hai:

```text
Realme 11 Pro (NEXORA app)
      │  HTTPS + X-Device-Token
      ▼
Yeh backend (FastAPI + Uvicorn)  ← AI provider key SIRF yahan rehti hai
      │  HTTPS
      ▼
AI provider (Gemini / Groq / OpenAI / OpenRouter)
```

Phone mein **kabhi AI key nahi** jaati. Phone ke paas sirf ek **device token** hota hai, jise aap kabhi bhi badal sakte ho.

---

## 1. Kya kya chahiye

| Cheez | Detail |
|---|---|
| Python | **3.11 ya 3.12 ya 3.13** (Windows installer, "Add python.exe to PATH" tick) |
| Internet | dependency install aur AI calls ke liye |
| AI provider key | **free tier possible** — neeche dekho |
| Hosting | local laptop (testing) ya koi HTTPS host (exhibition ke liye) |

Dependencies (bahut halki): `fastapi`, `uvicorn`, `httpx`, `python-dotenv` — sab already pinned hain `requirements.txt` mein.

---

## 2. AI provider — free ya paid? (sach)

**A. Google AI Studio (Gemini) — recommended shuruaat**
- Key free ban jaati hai, **credit card nahi chahiye**.
- Free tier mein **Flash / Flash-Lite** models (Pro models paid hain). Community reports: lagbhag **10–15 requests/minute** aur **~1,500 requests/day** — exact limits aapke project ke AI Studio page par dikhte hain.
- **Privacy note:** free tier mein Google prompts ko products improve karne ke liye use kar sakta hai. Isliye exhibition mein **personal/private cheezein mat bolna**.
- Paid tier par bahut kam rate hai (per 1M tokens), lekin aapke school demo ke liye free tier kaafi hai.

**B. Groq — bahut fast, OpenAI-compatible**
- Free tier, **card nahi chahiye**. Lagbhag **30 requests/minute**, chhote models par **~14,400/day**, bade models par **~1,000/day** (limits badalte rehte hain).
- Base URL: `https://api.groq.com/openai/v1`
- Aapko sirf `.env` badalna hai: `AI_PROVIDER=openai_compatible`, `OPENAI_API_KEY=...`, `OPENAI_MODEL=...`, `OPENAI_BASE_URL=https://api.groq.com/openai/v1`.

**C. OpenAI / OpenRouter**
- **OpenAI: PAID hai** — platform.openai.com par pehle billing/credits add karne padte hain (free tier nahi hai). Key bani ho par balance 0 ho, to app imaandaari se "abhi jawaab nahi mil paaya" bolega.
- Exact lines (`.env` mein):
  ```text
  AI_PROVIDER=openai_compatible
  OPENAI_API_KEY=sk-...                        <- apni OpenAI key
  OPENAI_MODEL=gpt-4o-mini                     <- dashboard par jo id aaj dikhe wahi likho
  OPENAI_BASE_URL=https://api.openai.com/v1
  ```
  Chhoti si rehat: `AI_PROVIDER=openai` ya `AI_PROVIDER=chatgpt` likhna bhi chalta hai — server usse apne aap `openai_compatible` samajh leta hai aur OpenAI ka base URL use karta hai.
- `gpt-5` / `o-series` jaise naye reasoning models bhi chal jaate hain (server unke liye sahi request format bhejta hai). Woh thoda mehnga pad sakta hai; `gpt-4o-mini` sabse sasta aur demo ke liye kaafi hai.
- OpenRouter: kuch `:free` models hain, par limits kam. Wahi 3 lines, base URL `https://openrouter.ai/api/v1`.

**Personality (cute + mazedaar):** NEXORA ka tone `app/config.py` ke `DEFAULT_SYSTEM_PROMPT` se set hota hai — ab woh chhote, pyaare, thoda playful (EMO jaisa) jawaab deta hai. Badalna ho to `.env` mein `SYSTEM_PROMPT=` ke saath apna instruction do (server restart karna mat bhoolna).

**E. Live internet info (naya, koi key nahi)**
- **Mausam** (open-meteo + wttr.in fallback), **taaza khabar** (Google News RSS) aur **facts** (Wikipedia) — sab free, koi API key nahi.
- Sirf tab chalta hai jab sawaal ko zaroorat ho ("aaj ka mausam", "taaza khabar", "2026 kaun jeeta", "search karo ..."). Normal sawaal pehle jaise tez rehte hain.
- Settings `.env` me: `WEB_SEARCH=1` (band karne ke liye `0`), `CITY=Patna`, `SEARCH_TIMEOUT_S=8`.
- Search fail ho jaye to jawaab rukta nahi — AI apne gyaan se jawaab deta hai aur imaandaari se bolta hai ki taaza jaankari nahi mili.

**G. Personality (Phase 5 — naya)**
- App `user_name` (optional) bhej sakti hai jab user ne apna naam bataya ho ("mera naam Aarav hai"). Robot usse pyaar se bula sakta hai.
- Server naam **store nahi karta** — sirf usi request ke prompt me jaata hai. Naam phone me (SharedPreferences) rehta hai.
- Mood, praise reaction, wink/dil/gussa wale chehre app me hote hain — server ko kuch karne ki zaroorat nahi.

**F. Camera vision (Phase 4 — naya)**
- Endpoint: `POST /v1/vision` — body me `text` (sawaal) + `image_b64` (JPEG/PNG base64).
- **Privacy:** tasveer kisi disk par save nahi hoti; sirf uss ek request me AI provider ko jaati hai, phir server use bhool jaata hai. History me sirf `[photo] <sawaal>` nishaan rehta hai.
- Free vision model: Groq par `qwen/qwen3.8-27b` (ya llama-4 vision). Server `VISION_MODELS` list me se pehla chalne wala chun leta hai — model retire ho jaye to kuch karne ki zaroorat nahi, agla apne aap chal jaata hai.
- Limits: `MAX_IMAGE_BYTES=350000` (app 720 px JPEG bhejti hai, ~60–120 KB), `VISION_TIMEOUT_S=40`.
- Band karna ho: `VISION_ENABLED=0` (phir app imaandaari se bolta hai "meri aankh band hai").

**D. Stub provider (koi key nahi)**
- `.env` mein `AI_PROVIDER=stub` aur `ALLOW_STUB_PROVIDER=1`.
- Yeh **nakli reply** deta hai — sirf yeh check karne ke liye ki phone ↔ server connection theek hai. Isse AI samajhna galat hoga.

> Kharche: sirf **tab** lagte hain jab aap paid tier ya paid provider choose karo. Free tier mein cost ₹0 rehti hai, magar daily limits khatam hone par app imaandaari se bolega “too many questions right now”.

**Hosting kharche:** host ke hisaab se — kuch services ka free tier hota hai (cold start ke saath, ya card verification maang sakte hain), aur ek chhota always-on VPS India mein roughly ₹300–₹600/month ke aas-paas pad sakta hai. Maine koi service recommend karke paisa nahi mangwaya — aap pehle laptop par test karo, phir jo chahiye wahi choose karo.

---

## 2.5 Sabse aasaan tareeka (Windows par 2 click)

1. `setup_windows.bat` par double-click — `.venv` banata hai, dependencies install karta hai, `.env` copy karta hai, aur **laptop ka IP** dikhata hai.
2. `notepad .env` — `GEMINI_API_KEY` + `DEVICE_TOKENS` bhar do.
3. `run_windows.bat` par double-click — server chalu (band karne ke liye Ctrl + C).

Phone me address/token bharna aur APK build karna: dekho **`NEXORA_Server_Setup_Hinglish.md`** (package ke root me).

## 3. Setup (Windows, step by step)

```powershell
# 1) backend folder mein jao (jo ZIP se aaya)
Set-Location C:\NexoraRobot\Phase3\backend

# 2) virtual environment banao
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # agar blocked ho: .\.venv\Scripts\activate.bat

# 3) dependencies install karo
pip install -r requirements.txt

# 4) .env banao
Copy-Item .env.example .env
notepad .env
```

`.env` mein ye zaroor bharna:

```
AI_PROVIDER=gemini
GEMINI_API_KEY=AIza...                     # AI Studio se copy kiya hua
GEMINI_MODEL=gemini-2.5-flash              # AI Studio par jo model id aaj available ho
DEVICE_TOKENS=mera-pehla-token-1234567890  # apna lamba random token
```

Random token banane ke liye:

```powershell
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

Wahi token **phone ki `BackendConfig.kt`** mein `DEVICE_TOKEN` ke andar daalna hai.

---

## 4. Server chalana / test karna

```powershell
# laptop par (phone ko same Wi-Fi par rakho)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

- **`--workers 1` zaroori hai** — conversation history RAM mein hai; 2 workers se context toot jaayega.
- Windows firewall pooche to **Private networks** ke liye allow karo.

Doosre PowerShell window mein test:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health

$headers = @{ "X-Device-Token" = "mera-pehla-token-1234567890" }
$body = @{ text = "नमस्ते नेक्सोरा, गुरुत्वाकर्षण क्या है?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat -Headers $headers -Body $body -ContentType "application/json"
```

Expected: `reply`, `language: "hi"`, aur `session_id`. Usi `session_id` ke saath dobara bhejne par NEXORA ko pichhli baat yaad rahegi.

Bina token bhejne par **401**, galat token par **401**, bahut lamba text par **422**, aur limit cross hone par **429** aana chahiye.

---

## 5. Phone ko is server se jodna (local Wi-Fi test)

1. Laptop ka Wi-Fi IP nikaalo: `ipconfig` → "IPv4 Address" (jaise `192.168.1.5`).
2. Phone ki ZIP mein `app/src/main/java/com/nexora/robot/BackendConfig.kt` kholo aur bharo:

```kotlin
const val SERVER_URL = "http://192.168.1.5:8000"
const val DEVICE_TOKEN = "mera-pehla-token-1234567890"
const val DEV_ALLOW_CLEARTEXT_HOST = "192.168.1.5"
```

3. `app/src/main/res/xml/network_security_config.xml` mein dev rule add karo:

```xml
<domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">192.168.1.5</domain>
</domain-config>
```

4. Android Studio se APK banao → phone par install. Ab “Hey Nexora” bolkar asli AI jawaab milega.

**Yeh HTTP sirf ghar/lab ke test ke liye hai.** Exhibition se pehle hosted **HTTPS** server par switch karo aur woh cleartext rule hata do (app by default plain HTTP refuse karti hai).

---

## 6. Exhibition ke liye hosting (laptop band hone ke baad bhi chale)

1. Backend ko kisi HTTPS host par deploy karo — koi bhi Python ASGI host chalega. Start command:

```text
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1
```

2. Host ke dashboard mein **environment variables** daalo (`.env` ki jagah): `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `DEVICE_TOKENS`.
3. URL milega jaise `https://nexora-xyz.onrender.com` → wahi `SERVER_URL` banao (HTTPS, bina trailing slash).
4. `DEV_ALLOW_CLEARTEXT_HOST` khaali kar do aur network security config se dev rule hata do.
5. Phone par dobara build karke install karo, aur “Hey Nexora” se ek sawaal poochho.

**Cold start:** kuch free hosts kuch minute idle ke baad sote hain; pehla jawaab dheera aa sakta hai (`THE ANSWER TOOK TOO LONG — TRY AGAIN` dikh sakta hai). Exhibition ke din exact time par server ko pehle ek baar “jaga” lo.

Docker pasand ho to folder mein `Dockerfile` bhi diya hai (`docker build -t nexora-backend .`).
Kuch hosts ke liye ready files bhi hain: **`Procfile`** (Render/Heroku-style `web:` command) aur **`render.yaml`** (Render ka blueprint — plan free, secrets dashboard se). Host kaise bhi ho, start command wahi rehni chahiye: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`.

---

## 7. Suraksha (kya protect hai, kya nahi)

- ✅ AI keys sirf server par, `.env` mein; `.gitignore` mein `.env` already blocked hai.
- ✅ Phone ka apna token; token badalne/delete karne se woh device turant band ho jaata hai.
- ✅ Rate limits (default 12/min, 300/day per device) — quota khatam hone se bachao.
- ✅ Input limit 500 characters, reply limit 220 tokens, session TTL 30 minit, history sirf 8 messages.
- ✅ Error replies chhote aur saaf hain — provider ka raw error ya key kabhi phone tak nahi jaata.
- ✅ `DELETE /v1/session/{id}` (token ke saath) — phone 10 minit idle ke baad ya topic badalne par purana context turant saaf kara sakta hai.
- ⚠️ Token APK ke andar hai. Koi chahe to APK se nikaal kar use kar sakta hai — isliye token ko **per-phone** rakho, doston ko mat do, aur zaroorat par badal do.
- ⚠️ Free tier par provider aapki baatein training ke liye use kar sakta hai — private/naam-address-password jaise data se bacho.
- ⚠️ Yeh service sirf apne phone ke liye hai. Public demo ke liye open API mat banao.

---

## 8. Tests (developer ke liye)

```powershell
pip install pytest
python -m pytest tests -q
```

8 tests: health (secret-free), token ke bina 401, galat token 401, Hindi jawaab + session context, empty/lamba text 422, rate limit 429, provider failures (auth/timeout/rate) ka sahi mapping, aur `DELETE /v1/session/{id}` (token ke bina 401, forget ke baad context saaf, dobara delete par bhi error nahi).

Yeh tests **stub provider** se chalte hain — internet ya API key ki zaroorat nahi.
