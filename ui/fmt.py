"""Human-readable number and date formats used across the UI (formatting, not styling)."""
import pandas as pd


def money(x) -> str:
    return "—" if x is None or pd.isna(x) else f"${float(x):,.0f}"


def pct(x, digits: int = 0) -> str:
    return "—" if x is None or pd.isna(x) else f"{float(x) * 100:.{digits}f}%"


def day(x) -> str:
    """Oct 9, 2026."""
    if x is None or (not isinstance(x, str) and pd.isna(x)) or x == "":
        return "—"
    t = pd.Timestamp(x)
    return f"{t:%b} {t.day}, {t.year}"


def plural(n: int, word: str, plural_word: str | None = None) -> str:
    return f"{n:,} {word if n == 1 else plural_word or word + 's'}"
