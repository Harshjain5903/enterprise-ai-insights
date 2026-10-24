from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

ZERO = Decimal("0")


def D(x) -> Decimal:
    if x is None:
        return ZERO
    if isinstance(x, Decimal):
        return x
    # str() first so floats don't drag binary noise in
    return Decimal(str(x))


def q2(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def safe_div(num: Decimal, den: Decimal) -> Decimal | None:
    if den == 0:
        return None
    return num / den


@dataclass(frozen=True)
class Delta:
    previous: Decimal
    current: Decimal
    absolute: Decimal
    pct: Decimal | None
    reason: str | None = None


def compare(previous, current) -> Delta:
    previous, current = D(previous), D(current)
    absolute = current - previous
    if previous == 0:
        return Delta(previous, current, absolute, None, "ZERO_BASELINE")
    return Delta(previous, current, absolute, absolute / abs(previous) * 100)


@dataclass(frozen=True)
class Decomposition:
    volume_effect: Decimal
    basket_effect: Decimal

    @property
    def total(self):
        return self.volume_effect + self.basket_effect


def decompose_revenue(orders0, aov0, orders1, aov1) -> Decomposition:
    """Split a revenue change into order-count and AOV parts.

    Uses midpoint weights so the two parts add up exactly to R1 - R0
    (R = orders * aov), instead of leaving an interaction term.
    """
    n0, n1, a0, a1 = D(orders0), D(orders1), D(aov0), D(aov1)
    volume = (n1 - n0) * (a0 + a1) / 2
    basket = (a1 - a0) * (n0 + n1) / 2
    return Decomposition(volume, basket)


def robust_z(value, history) -> Decimal | None:
    """(x - median) / (1.4826 * MAD). None if history is too short or flat."""
    hist = [D(h) for h in history]
    if len(hist) < 4:
        return None
    med = median(hist)
    mad = median([abs(h - med) for h in hist])
    if mad == 0:
        return None
    return (D(value) - med) / (Decimal("1.4826") * mad)


def moving_average(values) -> Decimal | None:
    vals = [D(v) for v in values]
    if not vals:
        return None
    return sum(vals, ZERO) / len(vals)
