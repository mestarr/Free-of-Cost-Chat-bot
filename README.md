# Free Crypto Chatbot

A **free**, crypto-focused AI chatbot. Uses either **Groq** (free cloud, no install) or **Ollama** (local).

## What you need

- **Python 3.10+**
- **Either** a free [Groq](https://console.groq.com) API key **or** [Ollama](https://ollama.com) installed locally

## Quick start (Groq – no Ollama)

1. Get a **free API key** at [console.groq.com](https://console.groq.com) (sign up, create a key).
2. From the project root:

   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   $env:GROQ_API_KEY = "gsk_your_key_here"
   uvicorn backend.main:app --reload
   ```

3. Open **http://127.0.0.1:8000** and chat. No Ollama needed.

## Quick start (Ollama – fully local)

1. Install [Ollama](https://ollama.com), then in a **new** terminal:

   ```powershell
   ollama pull llama3.2
   ```

2. From the project root (do **not** set `GROQ_API_KEY`):

   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn backend.main:app --reload
   ```

3. Open **http://127.0.0.1:8000**.

## Options

- **Groq**: `GROQ_API_KEY` = your key; optional `GROQ_MODEL` (default `llama-3.1-8b-instant`).
- **Ollama**: `OLLAMA_MODEL` (default `llama3.2`); `OLLAMA_URL` if Ollama runs on another machine.

## Project layout

- `backend/main.py` – FastAPI server, `/api/chat` endpoint, crypto system prompt, serves frontend.
- `frontend/index.html` – Single-page chat UI.
- `requirements.txt` – Python dependencies.

All cost is **zero** as long as you run Ollama locally (no cloud LLM usage).
