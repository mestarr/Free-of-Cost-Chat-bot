"""Paper trading outcome scoring."""

from backend.paper import classify_view_bias, infer_coin_id, score_outcome


def test_infer_btc():
    assert infer_coin_id("Should I buy BTC now?") == "bitcoin"


def test_classify_long_view():
    assert classify_view_bias("Buy bias") == "long"
    assert classify_view_bias("Sell bias") == "short"
    assert classify_view_bias("Hold") == "neutral"


def test_score_long_aligned():
    verdict, score = score_outcome("long", 2.5)
    assert verdict == "aligned"
    assert score == 100


def test_score_short_aligned_on_drop():
    verdict, score = score_outcome("short", -3.0)
    assert verdict == "aligned"
    assert score == 100


def test_score_neutral_small_move():
    verdict, _ = score_outcome("neutral", 0.5)
    assert verdict == "aligned"
