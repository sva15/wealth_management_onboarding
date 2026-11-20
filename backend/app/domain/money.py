"""Money formatting helpers (display and rationale text only; never used for calculation)."""
from decimal import Decimal


def format_inr(amount: Decimal, currency: str = "INR") -> str:
    """Indian digit grouping, e.g. INR 5,20,00,000.00."""
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount).quantize(Decimal('0.01')):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{currency} {whole}.{frac}"
