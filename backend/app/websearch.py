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
                    return f"Live weather (Open-Meteo): {text}"
    except Exception:  # noqa: BLE001 - search kabhi jawaab ko na roke
        pass
    try:  # fallback
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "curl/8"}) as client:
            await _be_polite()
            r = await client.get(f"https://wttr.in/{quote(city)}", params={"format": "j1"})
            cur = ((r.json() or {}).get("current_condition") or [{}])[0]
            if cur.get("temp_C"):
                desc = ((cur.get("weatherDesc") or [{}])[0].get("value") or "").strip()
                return (f"Live weather (wttr.in): {city} weather right now: {cur['temp_C']} C, {desc}, "
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


# ---- Wikimedia se baat karne ka saaf tarika (vc24s) --------------------------
# Wikimedia ka niyam: request me saaf tool naam + contact hona chahiye. Render jaisi
# cloud IP par bina contact wala UA 403 kha sakta hai, isliye ek hi jagah rakha hai.
_UA = {"User-Agent": "NexoraRobot/1.1 (Bihar school robotics project; nexora.robot@example.com)"}


async def wiki_lines(query: str, timeout: float, limit: int = 2) -> list[str]:
    """Wikipedia se seedha summary (facts ke liye sabse bharosemand)."""
    lang = "hi" if _DEVANAGARI.search(query) else "en"
    try:
        params = {
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrlimit": str(limit), "prop": "extracts", "exintro": "1",
            "explaintext": "1", "format": "json", "redirects": "1",
        }
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers=_UA) as client:
            await _be_polite()
            r = await client.get(f"https://{lang}.wikipedia.org/w/api.php", params=params)
        pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
        out = []
        for page in list(pages.values())[:limit]:
            extract = _short(_strip_html(page.get("extract") or ""), 300)
            if extract:
                out.append(f"Reference ({page.get('title', '')}): {extract}")
        if out:
            return out
    except Exception:  # noqa: BLE001
        pass
    # Doosra rasta (vc24s): api.wikimedia.org - alag host, wahi jaankari. Kuch cloud
    # IP par purana /w/api.php block hota hai par yeh khulta hai.
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                     headers=_UA) as client:
            s = await client.get(f"https://api.wikimedia.org/core/v1/wikipedia/{lang}/search/page",
                                 params={"q": query, "limit": str(limit)})
        pages = (s.json() or {}).get("pages") or []
        out = []
        for page in pages[:limit]:
            blurb = _strip_html(page.get("description") or page.get("excerpt") or "")
            blurb = _short(blurb, 300)
            if blurb:
                out.append(f"Reference ({page.get('title', '')}): {blurb}")
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
        line = f"Live fact (Wikipedia): the current {office_en.title()} of {place_en.title()} is {person_name}."
    if line and want_party and person_name:
        # Party sawaal: us aadmi ke page se party bhi laga do ("... is X, of the Y party.").
        party = await person_party_line(person_name, timeout)
        if party:
            line = (line.rstrip(".") + party_phrase(party)).rstrip(".") + "."
    _cache_put(key, line)
    return line


_WD_API = "https://www.wikidata.org/w/api.php"
_WD_UA = _UA   # (vc24s) ek hi saaf UA poore server par


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
    # Do not silently substitute a stored name for a current office. If live sources fail,
    # the research layer reports that current information could not be verified.
    line = None
    if name:
        suffix = party_phrase(party).rstrip(".") if party else ""
        line = (f"Live fact (Wikipedia): the current {portfolio_en.title()} Minister of "
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
                lines = [f"Live fact (Wikipedia): the party of {pretty} is {party}."]
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
    # Do not silently use a dated snapshot for a current office holder. An empty result is
    # surfaced as live-research uncertainty instead of a confident but potentially stale claim.
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


# ---- /v1/netcheck (vc24s): server se kaun sa bahar ka source khula hai ---------
async def netcheck(timeout: float = 6.0) -> dict:
    """Har source ko chhota GET - asli status/bytes ya error. Debug ke liye."""
    targets = [
        ("wikipedia_api", "https://en.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json"),
        ("wikipedia_raw", "https://en.wikipedia.org/w/index.php?title=Bihar&action=raw"),
        ("wikimedia_api", "https://api.wikimedia.org/core/v1/wikipedia/en/page/Bihar"),
        ("wikidata_sparql", "https://query.wikidata.org/sparql?query=SELECT%20%3Fx%20WHERE%20%7B%20wd%3AQ2%20wdt%3AP31%20%3Fx%20%7D%20LIMIT%201&format=json"),
        ("google_news", "https://news.google.com/rss/search?q=bihar+cm&hl=en-IN&gl=IN&ceid=IN:en"),
        ("open_meteo", "https://api.open-meteo.com/v1/forecast?latitude=25.6&longitude=85.1&current=temperature_2m"),
        ("groq_api", "https://api.groq.com/openai/v1/models"),
    ]
    report: dict = {}
    for name, url in targets:
        began = time.time()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                         headers=_UA) as client:
                r = await client.get(url)
            report[name] = {"status": r.status_code, "bytes": len(r.content),
                            "ms": int((time.time() - began) * 1000)}
        except Exception as exc:  # noqa: BLE001
            report[name] = {"error": f"{type(exc).__name__}: {exc}"[:160],
                            "ms": int((time.time() - began) * 1000)}
    return report
