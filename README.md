# Crypto drug

A **free**, crypto-focused AI chatbot with a web UI and **live USD spot prices** (CoinGecko). The brain uses either **Groq** (free cloud, no local install) or **Ollama** (fully local).

## What you need

- **Python 3.10+**
- **Either** a free [Groq](https://console.groq.com) API key **or** [Ollama](https://ollama.com) installed locally

## Project layout

| Path | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app: `/api/chat`, `/api/prices`, serves static frontend |
| `backend/prices.py` | CoinGecko live prices (cached ~60s), shared with chat context |
| `frontend/index.html` | Page structure only |
| `frontend/css/style.css` | Layout and visual design |
| `frontend/js/app.js` | Chat + price panel behavior |
| `requirements.txt` | Python dependencies |
| `.env` | Optional: `GROQ_API_KEY` (copy from `.env.example`) |

## Quick start (Groq – no Ollama)

1. Create a **free API key** at [console.groq.com](https://console.groq.com).
2. In the project root, copy `.env.example` to `.env` and set:

   ```env
   GROQ_API_KEY=gsk_your_key_here
   ```

3. Install and run (from the project root):

   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   python -m pip install -r requirements.txt
   python -m uvicorn backend.main:app --reload
   ```

4. Open **http://127.0.0.1:8000**. You should see the chat and the **Live prices** panel on the right (below the chat on narrow screens).

## Quick start (Ollama – fully local)

1. Install [Ollama](https://ollama.com), then:

   ```powershell
   ollama pull llama3.2
   ```

2. Do **not** set `GROQ_API_KEY` in `.env` (or remove it). Run the server as above.

## Configuration

- **Groq**: `GROQ_API_KEY` in `.env`; optional `GROQ_MODEL` (default `llama-3.1-8b-instant`).
- **Ollama**: optional `OLLAMA_MODEL` (default `llama3.2`), `OLLAMA_URL` if Ollama runs elsewhere.

## Live prices

- The UI polls **`GET /api/prices` every second** so you do not need to refresh the page.
- CoinGecko is **not** queried every second (that would hit rate limits). The server caches responses for **10 seconds** by default (`PRICE_CACHE_SECONDS` in `.env` if you want a different interval).
- Each chat request uses the same cached snapshot in context (from `backend/prices.py`).
- Data comes from [CoinGecko](https://www.coingecko.com/en/api) public API (free tier; rate limits may apply). No CoinGecko key is required for basic use.

## Cost

- **Groq**: free tier with limits; check Groq’s current policy.
- **Ollama**: no API cost when running models locally.
- **CoinGecko**: public API within free-tier limits.

## Editing the UI

- Change **structure** in `frontend/index.html`.
- Change **look** (colors, spacing, layout) in `frontend/css/style.css`.
- Change **behavior** (chat, price refresh) in `frontend/js/app.js`.

After edits, refresh the browser; with `--reload`, the server restarts when Python files change.
