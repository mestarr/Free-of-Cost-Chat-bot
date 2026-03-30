# Crypto ChatPal

A **free**, crypto-focused AI chatbot with a web UI, **live USD spot prices** (CoinGecko), and **headlines from crypto RSS feeds** (CoinDesk, Decrypt, BeInCrypto). The brain uses either **Groq** (free cloud, no local install) or **Ollama** (fully local).

## What you need

- **Python 3.10+**
- **Either** a free [Groq](https://console.groq.com) API key **or** [Ollama](https://ollama.com) installed locally

## Project layout

| Path | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app: `/api/chat`, `/api/prices`, `/api/news`, serves static frontend |
| `backend/prices.py` | CoinGecko live prices (cached), shared with chat context |
| `backend/news.py` | RSS headline aggregation (cached), shared with chat context |
| `frontend/index.html` | Page structure only |
| `frontend/css/style.css` | Layout and visual design |
| `frontend/js/app.js` | Chat + prices + news panel behavior |
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

4. Open **http://127.0.0.1:8000**. You should see the chat and the **Live prices** + **Latest news** column on the right (stacked below the chat on narrow screens).

## Quick start (Ollama – fully local)

1. Install [Ollama](https://ollama.com), then:

   ```powershell
   ollama pull llama3.2
   ```

2. Do **not** set `GROQ_API_KEY` in `.env` (or remove it). Run the server as above.

## Configuration

- **Groq**: `GROQ_API_KEY` in `.env`; optional `GROQ_MODEL` (default `llama-3.1-8b-instant`).
- **Ollama**: optional `OLLAMA_MODEL` (default `llama3.2`), `OLLAMA_URL` if Ollama runs elsewhere.
- **News RSS**: optional `NEWS_CACHE_SECONDS` (default `300`), `NEWS_MAX_HEADLINES_LLM` (default `18`), `NEWS_USER_AGENT`.

## Headlines (RSS)

Default feeds (**crypto news**):

- **[CoinDesk](https://www.coindesk.com/)** — `https://www.coindesk.com/arc/outboundfeeds/rss/`
- **[Decrypt](https://decrypt.co/)** — `https://decrypt.co/feed`
- **[BeInCrypto](https://beincrypto.com/)** — `https://beincrypto.com/feed/` (often returns **HTTP 403** to automated/server IPs; if so, that source contributes no items until it succeeds)

- **`GET /api/news`** — JSON for the UI (cached).
- **Chat** — each request includes a text snapshot of recent headlines (source + title + link + short snippet) so the model can discuss them **with attribution**.

Sentiment labels in the UI are **rough keyword heuristics**, not financial analysis.

## Live prices

- The UI polls **`GET /api/prices` every second** so you do not need to refresh the page.
- CoinGecko is **not** queried every second (that would hit rate limits). The server caches responses for **10 seconds** by default (`PRICE_CACHE_SECONDS` in `.env` if you want a different interval).
- Each chat request uses the same cached snapshot in context (from `backend/prices.py`).
- Data comes from [CoinGecko](https://www.coingecko.com/en/api) public API (free tier; rate limits may apply). No CoinGecko key is required for basic use.

## Cost

- **Groq**: free tier with limits; check Groq’s current policy.
- **Ollama**: no API cost when running models locally.
- **CoinGecko**: public API within free-tier limits.

## Attaching text files (e.g. README.md)

- In the chat input area, use **Attach** to add up to **5** text files per send.
- Allowed: common text types (e.g. `.md`, `.txt`, `.csv`, `.json`, `.log`) and other `text/*` MIME types; each file is capped at **256 KB** on the client.
- File contents are read **in the browser** and merged into the outgoing user message for that request only. They are **not** uploaded to a separate server storage.
- Saved chat history stores your message plus a line like `(Attached: README.md)` so you know what you sent; it does **not** re-store full file bodies. To discuss the same file again in a later turn, attach it again.
- The API accepts up to **200,000** characters per message body (including merged attachment text); very large pastes may be rejected.

## Light / dark theme

- Use the **Light** and **Dark** buttons in the page header to switch themes.
- The choice is saved in the browser (`localStorage` key `cryptochatpal_theme`) and applied on the next visit.

## Session desk

- Open **Session desk** from the chat toolbar for a **Market pulse** (0–100): a blend of your **watchlist** 24h volatility and **RSS headline** sentiment counts from the left column.
- **Stance log**: when the assistant replies using the structured trade format (lines like `View:`, `Confidence:`, `Score:`), those fields are parsed and appended automatically (stored in `localStorage` under `cryptochatpal_stance_ledger`, last 24 entries).
- **Export snapshot** downloads a JSON file with the current pulse readout and stance log (handy for journaling or sharing what the UI “saw” in that session).

## Editing the UI

- Change **structure** in `frontend/index.html`.
- Change **look** (colors, spacing, layout) in `frontend/css/style.css`.
- Change **behavior** (chat, price refresh, news refresh) in `frontend/js/app.js`.

After edits, refresh the browser; with `--reload`, the server restarts when Python files change.
