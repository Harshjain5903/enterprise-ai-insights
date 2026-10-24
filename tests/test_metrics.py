from decimal import Decimal

from insights.metrics import compare, decompose_revenue, robust_z, safe_div, q2, D


def test_compare_basic():
    d = compare(Decimal("100"), Decimal("92"))
    assert d.absolute == Decimal("-8")
    assert d.pct == Decimal("-8")


def test_compare_zero_baseline():
    d = compare(0, 20)
    assert d.pct is None
    assert d.reason == "ZERO_BASELINE"
    assert d.absolute == 20


def test_compare_negative_baseline_uses_abs():
    # -50 -> -25 is an improvement, should come out positive
    assert compare(-50, -25).pct == Decimal("50")


def test_float_input_no_binary_noise():
    assert D(0.1) + D(0.2) == Decimal("0.3")


def test_safe_div():
    assert safe_div(Decimal(1), Decimal(0)) is None
    assert safe_div(Decimal(10), Decimal(4)) == Decimal("2.5")


def test_decomposition_adds_up():
    n0, a0 = 1000, Decimal("100.00")
    n1, a1 = 970, Decimal("94.85")
    dec = decompose_revenue(n0, a0, n1, a1)
    assert q2(dec.total) == q2(n1 * a1 - n0 * a0)
    assert dec.volume_effect < 0 and dec.basket_effect < 0


def test_robust_z():
    hist = [100, 102, 98, 101, 99, 100]
    assert robust_z(100, hist) == 0
    assert robust_z(130, hist) > 10
    assert robust_z(100, [1, 2]) is None
    assert robust_z(5, [3, 3, 3, 3]) is None
