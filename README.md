# Crypto ChatPal

A **free**, crypto-focused AI chatbot with a web UI, **live USD spot prices** (CoinGecko), and **headlines from crypto RSS feeds** (CoinDesk, Decrypt, BeInCrypto). The brain uses either **Groq** (free cloud, no local install) or **Ollama** (fully local).

There is **no separate frontend dev server** — `uvicorn` serves `frontend/` and the API on **http://127.0.0.1:8000**.

## What you need

- **Python 3.10+**
- **Either** a free [Groq](https://console.groq.com) API key **or** [Ollama](https://ollama.com) installed locally

## Project layout

| Path | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app: chat, prices, news, paper outcomes; serves static `frontend/` |
| `backend/llm_tools.py` | Groq tools (prices, headlines, macro, F&G, on-chain, trade card) |
| `backend/paper.py` | Paper-trade outcome scoring vs historical CoinGecko USD |
| `backend/memory.py` | Per-user vector memory (sqlite-vec + sentence-transformers) |
| `backend/war_room.py` | Bull / Bear / Referee war-room prompts and message builders |
| `backend/mcp_server.py` | stdio MCP server for Claude Desktop, Cursor, ChatGPT |
| `backend/prices.py` | CoinGecko live prices (cached), shared with chat context |
| `backend/news.py` | RSS headline aggregation (cached), shared with chat context |
| `backend/accounts.py` | SQLite API keys (hashed) and per-day usage counters |
| `backend/saas_middleware.py` | Optional `/api/*` auth, rate limits, usage on successful responses |
| `backend/admin_routes.py` | `POST /api/admin/keys`, `GET /api/me/usage` |
| `backend/redis_cache.py` | Redis read-through cache helpers and shared rate-limit windows |
| `frontend/index.html` | Page structure only |
| `frontend/css/style.css` | Layout and visual design |
| `frontend/js/app.js` | Chat + prices + news panel behavior |
| `requirements.txt` | Python dependencies |
| `docker-compose.yml` | Optional Redis (`--profile cache`) + named volume for `.data` (accounts DB) |
| `.env` / `.env.example` | Groq/Ollama, optional `REDIS_URL`, optional `CCP_*` tenant settings |

## Quick start (Groq – no Ollama)

1. Create a **free API key** at [console.groq.com](https://console.groq.com).
2. In the project root, copy `.env.example` to `.env` and set:

   ```env
   GROQ_API_KEY=gsk_your_key_here
   ```

3. Install and run (from the project root):

   ```powershell
   py -3.14 -m venv venv
   .\venv\Scripts\activate
   python -m pip install -r requirements.txt
   python -m uvicorn backend.main:app --reload --reload-dir backend --reload-dir frontend
   ```

   Do **not** use bare `--reload` without `--reload-dir` — StatReload watches the whole project including `venv/` and can loop forever or block port 8000.

   On Windows, prefer **`py -3.14 -m venv`** (python.org) over MSYS2’s `python` — mingw builds often lack wheels for `pydantic-core` / `watchfiles` and fail without Rust.

   If imports fail (`BaseMetadata`, `anyio.to_thread`), the venv may be corrupted — purge pip cache and reinstall: `python -m pip cache purge` then `python -m pip install --no-cache-dir -r requirements.txt`.

4. Open **http://127.0.0.1:8000**. You should see the chat and the **Live prices** + **Latest news** column on the right (stacked below the chat on narrow screens).

## Quick start (Ollama – fully local)

1. Install [Ollama](https://ollama.com) (Windows installer) and keep the app running (system tray).
2. Pull the default model:

   ```powershell
   ollama pull llama3.2
   ollama list
   ```

3. In `.env`, **remove or leave empty** `GROQ_API_KEY`. If a `gsk_…` key is still set, the app uses **Groq**, not Ollama.
4. Optional: `OLLAMA_MODEL=llama3.2`, `OLLAMA_URL=http://localhost:11434`.
5. Run the server as in the Groq quick start (same `uvicorn` command).
6. Open **http://127.0.0.1:8000** and chat.

**Ollama-only limits:** no chart screenshot vision, no Groq tool loop / multi-model routing — text chat, prices, news, and session desk still work. Test Ollama: `ollama run llama3.2 "hi"`.

## Configuration

Use **`.env.example`** as the checklist for every variable (each is commented there).

### LLM and context

| If `.env` has… | Backend uses |
|----------------|--------------|
| `GROQ_API_KEY=gsk_…` (non-empty) | **Groq** (cloud) |
| No / empty `GROQ_API_KEY` | **Ollama** at `OLLAMA_URL` (default `http://localhost:11434`) |

- **Groq**: `GROQ_API_KEY`; optional `GROQ_MODEL` when `GROQ_MODEL_ROUTING=0`. With routing on (default): `GROQ_FAST_MODEL` (8b Q&A), `GROQ_TRADE_MODEL` (70b trades), `GROQ_VISION_MODEL` (chart images). See `.env.example`.
- **Ollama**: `OLLAMA_MODEL` (default `llama3.2`), `OLLAMA_URL` if Ollama runs elsewhere.
- **News RSS**: optional `NEWS_CACHE_SECONDS` (default `300`), `NEWS_MAX_HEADLINES_LLM` (default `18`), `NEWS_USER_AGENT`.

**Port 8000 busy?** Stop the old `uvicorn` process or use `--port 8001`.

### Shared Redis (optional)

If **`REDIS_URL`** is set (for example `redis://redis:6379/0` when using Docker Compose), the server uses Redis for **price and news read-through cache** and for **per-key / per-IP rate limits**, so behavior is consistent across **multiple workers**. Without Redis, those features fall back to **in-process memory** (fine for one process; not shared across processes).

Compose: `docker compose --profile cache up -d`, then point `REDIS_URL` at the `redis` service as in `.env.example`.

### API keys, usage, and auth (optional)

By default the app stays **open** (no tenant API key). For SaaS-style controls:

| Variable | Role |
|----------|------|
| `CCP_AUTH_MODE` | `off` (default), `optional` (validate key when present), or `required` (HTTP `/api/*` and live WebSocket need a valid key). |
| `CCP_ADMIN_SECRET` | Protects **`POST /api/admin/keys`** via header **`X-CCP-Admin-Secret`**. Use a long random value in production. |
| `CCP_ACCOUNTS_DB` | Optional SQLite path; default **`.data/ccp_accounts.sqlite`** (gitignored). |
| `CCP_KEY_PEPPER` | Pepper for hashing stored keys; **change the default in production**. |
| `CCP_RATE_LIMIT_PER_KEY`, `CCP_RATE_LIMIT_ANON_IP`, `CCP_RATE_LIMIT_WINDOW_SEC` | Fixed-window limits; anonymous IP bucket applies without a key or when auth is off/optional. |

**Bootstrap a key**: `POST /api/admin/keys` with the admin header; optional JSON body `{"label":"my laptop"}`. The JSON response includes **`api_key` once** (prefix `ccp_sk_…`); the server only stores a hash.

**Calling the API**: header **`X-CCP-API-Key`** or **`Authorization: Bearer <your ccp_sk_… key>`**. **`GET /api/me/usage?days=14`** returns daily request totals for that key.

**Web UI with `required` auth**: set browser **`localStorage`** key **`ccp_api_key`** to your secret so requests send **`X-CCP-API-Key`** and the live socket uses **`?api_key=...`** (custom WebSocket headers are awkward in browsers).

**Usage accounting**: successful `/api/*` responses increment per-key daily counters when a key is attached. Paths such as **`/api/health`**, **`/api/metrics`**, **`/api/admin`**, **`/docs`**, **`/redoc`**, and **`/openapi.json`** are excluded from that behavior.

**Docker**: `docker-compose.yml` mounts a named volume at **`/app/.data`** so the default accounts database survives container recreation.

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

## Voice input / output (Web Speech API)

- **No server or API cost** — uses the browser’s built-in speech recognition and synthesis (Chrome/Edge work best).
- **Mic** (input row): tap to start/stop dictation; transcript fills the message box (edit, then Send).
- Toolbar **Mic** / **Speaker**: toggle voice input and **auto-read** new assistant replies.
- Each assistant message gets **Listen** / **Stop** for on-demand read-aloud.
- Requires microphone permission for input; uses `localStorage` keys `cryptochatpal_voice_input` and `cryptochatpal_voice_output`.

## Shareable watchlists

- In the **Coin prices** editor, click **Share watchlist** — a short URL like `http://127.0.0.1:8000/#wl.Yml0Y29...` is copied to the clipboard.
- Anyone opening that link gets a **confirm prompt** to load the watchlist (replaces their current one).
- **No server upload** — the entire list is encoded in the URL hash (base64url, `#wl.` prefix). Compact enough to paste in chat, DMs, or social posts.
- Supports up to 30 coins; coin ids and short labels are preserved.

## Light / dark theme

- Use the **Light** and **Dark** buttons in the page header to switch themes.
- The choice is saved in the browser (`localStorage` key `cryptochatpal_theme`) and applied on the next visit.

## Streaming replies

- The UI calls **`POST /api/chat/stream`**, which streams the assistant reply as **NDJSON** (one JSON object per line: text chunks in `{"c":"..."}`, then `{"done":true,"model":"..."}`).
- Groq and Ollama both stream; the same price and news context is injected as for `/api/chat`.

## Agent mode (multi-step tool chaining)

- Turn on **Agent** in the chat toolbar (saved in `localStorage` as `cryptochatpal_agent_mode`).
- **Groq only** — requires `GROQ_API_KEY` and `LLM_TOOLS=1` (default). Ollama does not run the tool loop.
- The model chains tools before answering, e.g. live prices → Binance funding/OI → Fear & Greed → headlines/macro → structured trade card.
- Extra tools: `get_fear_greed`, `get_onchain_derivatives` (plus the standard price/headline/macro/trade tools).
- Uses the **70b trade model** with up to **`LLM_AGENT_MAX_TOOL_ROUNDS`** steps (default **12**; normal chat uses **8**).
- While thinking, the status line shows steps like `Agent: Funding & flows (step 2)` via NDJSON `{"agent_step":{...}}`.
- Request body: `"agent_mode": true` on `/api/chat` and `/api/chat/stream`.

## War room (multi-agent debate)

- Turn on **War room** in the chat toolbar (mutually exclusive with **Agent**; saved as `cryptochatpal_war_room_mode`).
- **Groq only** — runs three calls: **Bull** and **Bear** in parallel (8b, injected context), then **Referee** (70b) synthesizes the final answer.
- UI shows a **3-panel view**: Bull | Bear on top, Referee final answer below (also in the main reply area).
- Referee may call `emit_trade_analysis` for structured trade output on buy/sell questions.
- Slower (~3× API calls) but useful for trade decisions. Optional `WAR_ROOM_DEBATE_MAX_TOKENS` (default `1024`) caps bull/bear length.
- Request body: `"war_room_mode": true`. Does not support chart image uploads yet.

## MCP server (Claude Desktop, Cursor, ChatGPT)

Expose the same **price / news / macro** tools to any MCP client — no Groq key needed for data tools.

### Tools

| Tool | Description |
|------|-------------|
| `get_prices` | CoinGecko USD spot + 24h change |
| `get_crypto_headlines` | Crypto RSS headlines |
| `get_macro_snapshot` | Oil/metals + Fed headlines |
| `get_fear_greed` | Fear & Greed index |
| `get_onchain_derivatives` | Binance funding, OI, positioning |
| `get_macro_radar` | FOMC / CPI / SEC within 48h |

### Run (stdio)

From the project root (venv activated):

```powershell
python -m backend.mcp_server
```

Or double-click **`run_mcp.bat`** on Windows. The process speaks MCP over stdin/stdout — leave it running; the client spawns it automatically when configured.

### Cursor

1. **Settings → MCP → Add server** (or edit `~/.cursor/mcp.json`).
2. Copy paths from **`mcp_config.example.json`** — set `command` to your venv Python and `cwd` to this repo.
3. Restart Cursor; tools appear as **cryptochatpal**.

Example:

```json
{
  "mcpServers": {
    "cryptochatpal": {
      "command": "C:/Users/YOU/.../CryptoChatPal/venv/Scripts/python.exe",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "C:/Users/YOU/.../CryptoChatPal"
    }
  }
}
```

### Claude Desktop

Edit `%APPDATA%\\Claude\\claude_desktop_config.json` with the same `mcpServers` block (use forward slashes in paths).

### ChatGPT

Add a **custom MCP connector** (Desktop app → Settings → Connectors) pointing at the same command + args if your plan supports local MCP.

### Notes

- Install deps: `pip install -r requirements.txt` (includes `mcp`).
- Uses `.env` for optional `REDIS_URL`, cache TTLs, etc. — same as the web app.
- **Do not** run uvicorn and debug-print inside the MCP process; stdout is the protocol stream.

## Portfolio (local-first)

- In the **right column**, under the price editor, **Portfolio** lets you track **holdings** by CoinGecko id: **amount** and optional **average buy price (USD)**.
- **Value** and **unrealized P/L** use the same live prices as the watchlist (`GET /api/prices`). Coins only in the portfolio are still fetched (IDs are merged into one request).
- Everything is stored in **`localStorage`** (`cryptochatpal_portfolio`); nothing is sent to a server except the existing public price API.

## Macro radar banners

- **FOMC**, **CPI**, and **SEC** events from official `.gov` schedules (Fed, BLS, SEC), cached ~1h.
- Shows amber banners above the chat when something falls in the next **48 hours** (configurable via `MACRO_RADAR_WINDOW_HOURS`).
- **`GET /api/macro/radar`** — JSON for the UI; the same summary is injected into chat context when events are active.
- WebSocket `macro` pushes include a `radar` field when live feed is connected.

## Vector memory (RAG)

- Each browser gets a stable **`memory_user_id`** (`localStorage` → `cryptochatpal_memory_user`, also sent as `X-CCP-Memory-User`).
- After each chat turn, user + assistant text is embedded and stored in **sqlite-vec** (`.data/ccp_memory.sqlite` by default).
- Before the next reply, the server retrieves the top similar past snippets and injects them as a system block.
- **Session desk → Vector memory** shows chunk count; **Clear my memory** calls `DELETE /api/memory`.
- Requires `pip install -r requirements.txt` (`sqlite-vec`, `sentence-transformers`, `numpy`). First chat after install downloads the embedding model (~80MB). Set `CCP_MEMORY_ENABLED=0` to disable.
- With **CCP API keys**, memory is scoped per key (`key_<id>`) instead of the browser id.

## Session desk

- Open **Session desk** from the chat toolbar for a **Market pulse** (0–100): a blend of your **watchlist** 24h volatility and **RSS headline** sentiment counts from the left column.
- **Paper trading / backtest**: each `emit_trade_analysis` reply is stored in `localStorage` (`cryptochatpal_paper_trades`) with entry USD, coin id, and full structured fields. After **24h** and **7d**, the UI calls **`GET /api/paper/outcome`** (CoinGecko historical USD) and scores **aligned / mixed / missed** vs the stated view (buy/sell/hold). Optional `coin_gecko_id` in the tool output improves asset detection.
- **Stance log**: when the assistant replies using the structured trade format (lines like `View:`, `Confidence:`, `Score:`), those fields are parsed and appended automatically (stored in `localStorage` under `cryptochatpal_stance_ledger`, last 24 entries).
- **Export snapshot** downloads a JSON file with the current pulse readout, paper trades, and stance log (handy for journaling or sharing what the UI “saw” in that session).

## Editing the UI

- Change **structure** in `frontend/index.html`.
- Change **look** (colors, spacing, layout) in `frontend/css/style.css`.
- Change **behavior** (chat, price refresh, news refresh) in `frontend/js/app.js`.

After edits, refresh the browser; with `--reload`, the server restarts when Python files change.

## Tests and lint

From the project root (with your venv activated):

```powershell
python -m pip install -r requirements.txt
ruff check backend tests
pytest -q
```
