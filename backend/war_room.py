"""
Multi-agent war room: Bull and Bear analysts debate, Referee synthesizes the final answer.
Uses injected price/news context only (no tool loop on bull/bear) to limit API cost.
"""
from __future__ import annotations

BULL_SYSTEM = """You are the BULL analyst in a crypto war room debate.

Your job: make the strongest honest bullish case using ONLY data in this request
(system blocks, user text, prior turns).
- Cite live prices, headlines, and macro context when present; never invent numbers or stories.
- 4–8 concise bullets or short paragraphs: upside drivers, momentum, supportive news, favorable risk/reward.
- Acknowledge one key risk in one line, then explain why bulls still have an edge.
- Do NOT write the final user answer; do NOT play devil's advocate; stay bullish but factual.
- Match the user's language."""

BEAR_SYSTEM = """You are the BEAR analyst in a crypto war room debate.

Your job: make the strongest honest bearish / cautious case using ONLY data in this request.
- Cite live prices, headlines, and macro context when present; never invent numbers or stories.
- 4–8 concise bullets or short paragraphs: downside risks, weak momentum, adverse news, poor R:R, macro headwinds.
- Acknowledge one bullish counterpoint in one line, then explain why caution still wins.
- Do NOT write the final user answer; do NOT cheerlead; stay bearish but factual.
- Match the user's language."""

REFEREE_SYSTEM = """You are the REFEREE in a crypto war room. Two analysts (Bull and Bear) debated the user's question.

Your job: synthesize BOTH cases into ONE clear final answer for the user.
- Weigh evidence from injected context and the bull/bear write-ups; call out where they agree or conflict.
- For trade / buy / sell / hold questions: use the standard decision framework (View, Confidence, Score, Plan, risks).
- You may call emit_trade_analysis once when the user wants structured trade output
  (not for yes/no-only format constraints).
- Be decisive but probabilistic; lower confidence when bull and bear both have strong points.
- Start with a one-line verdict, then structured detail. Match the user's language.
- End trade / buy / sell / hold answers with: "Disclaimer: Educational analysis only — not financial advice. Crypto is high risk; AI can be wrong. Do your own research before investing." (translate if the user writes in another language)."""


def _system_messages(base_messages: list[dict]) -> list[dict]:
    return [dict(m) for m in base_messages if m.get("role") == "system"]


def _conversation_messages(base_messages: list[dict]) -> list[dict]:
    return [dict(m) for m in base_messages if m.get("role") in ("user", "assistant")]


def last_user_text(base_messages: list[dict]) -> str:
    for m in reversed(base_messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"].strip()
    return ""


def build_debate_messages(base_messages: list[dict], persona: str) -> list[dict]:
    """Context + persona system prompt + conversation for Bull or Bear."""
    overlay = BULL_SYSTEM if persona == "bull" else BEAR_SYSTEM
    out = _system_messages(base_messages)
    out.append({"role": "system", "content": overlay})
    out.extend(_conversation_messages(base_messages))
    return out


def build_referee_messages(base_messages: list[dict], bull_text: str, bear_text: str) -> list[dict]:
    """Context + referee prompt + debate transcript as the final user turn."""
    question = last_user_text(base_messages) or "the user's question"
    conv = _conversation_messages(base_messages)
    if conv and conv[-1].get("role") == "user":
        conv = conv[:-1]

    debate_block = (
        f"Original user question:\n{question}\n\n"
        f"--- BULL analyst ---\n{bull_text.strip() or '(no bull case)'}\n\n"
        f"--- BEAR analyst ---\n{bear_text.strip() or '(no bear case)'}\n\n"
        "As REFEREE, write the final answer for the user. Synthesize both sides; "
        "use the decision framework when relevant."
    )

    out = _system_messages(base_messages)
    out.append({"role": "system", "content": REFEREE_SYSTEM})
    out.extend(conv)
    out.append({"role": "user", "content": debate_block})
    return out


def format_stored_assistant_text(bull: str, bear: str, referee: str) -> str:
    """Plain-text shape for chat history / memory ingestion."""
    parts = [
        "**War room — Bull**\n" + (bull or "").strip(),
        "**War room — Bear**\n" + (bear or "").strip(),
        "---\n" + (referee or "").strip(),
    ]
    return "\n\n".join(p for p in parts if p.strip())
