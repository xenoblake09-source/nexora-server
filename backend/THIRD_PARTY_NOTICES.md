# NEXORA backend — third-party notices

Yeh backend sirf in libraries ko use karta hai (versions jo test kiye gaye: `requirements.txt` dekho).
Sab licenses permissive hain; code redistribute/publish karne ke liye credit dena kaafi hai
(kuch BSD/MIT clauses mein license text shaamil karna hota hai — apne public repo mein yeh file rakho).

| Package | Version (tested) | License |
|---|---|---|
| fastapi | 0.115.6 | MIT |
| starlette | 0.41.3 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-core | 2.46.5 | MIT |
| uvicorn | 0.34.0 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| httpcore | 1.0.9 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| anyio | 4.15.1 | MIT |
| idna | 3.20 | BSD-3-Clause |
| sniffio | 1.x | MIT / Apache-2.0 |
| click | 8.5.0 | BSD-3-Clause |
| python-dotenv | 1.0.1 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| annotated-types | 0.8.0 | MIT |
| certifi | 2026.7.22 | MPL-2.0 |
| watchfiles, websockets, httptools, uvloop, PyYAML | uvicorn[standard] extras | MIT / BSD-3-Clause |

Optional dev tool: **pytest** (MIT).

Notes:

- `certifi` (MPL-2.0) sirf CA certificate bundle hai; use karte waqt file-level changes ka source dena padta hai — hum ise modify nahi karte.
- Humara apna code (`app/`, `tests/`, `run.py`) is repo ka hai — aap free ho jo karna chahein.
- Yeh table **information** ke liye hai; legal advice nahi. Deploy karne se pehle apne host/publisher ki policies dekh lena.
