"""Groq multi-model routing heuristics."""

from backend.main import _is_education_intent, _is_trade_intent, resolve_groq_route


def test_trade_intent_buy_question():
    assert _is_trade_intent("Should I buy BTC now?")
    assert resolve_groq_route("Should I buy BTC now?")[0] == "trade"


def test_education_intent_definition():
    assert _is_education_intent("What is a funding rate?")
    assert not _is_trade_intent("What is a funding rate?")
    assert resolve_groq_route("What is a funding rate?")[0] == "fast"


def test_vision_route_with_images_flag():
    route, _model = resolve_groq_route("analyze this chart", has_images=True)
    assert route == "vision"


def test_trade_beats_generic_explain():
    assert resolve_groq_route("Explain whether I should sell ETH today")[0] == "trade"
