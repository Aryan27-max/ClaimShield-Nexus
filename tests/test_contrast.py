"""WCAG 2.2 contrast for every text / background token pair in both themes (AA: body text >= 4.5:1, large text
and UI components >= 3:1)."""
import pytest

from ui import style as U

TEXT_ON = ["bg", "surface", "surface-2"]


def _lum(hex_color: str) -> float:
    rgb = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pairs(theme: str):
    p = U.PALETTES[theme]
    body = [(f"{fg} on {bg}", p[fg], p[bg]) for fg in ("text", "text-2", "accent-text") for bg in TEXT_ON]
    body += [(f"{t}-text on {bg}", p[f"{t}-text"], p[bg]) for t in U.TONE.values() for bg in ("surface", f"{t}-bg")]
    body += [("white on button", "#FFFFFF", p["button"]), ("white on danger-button", "#FFFFFF", p["danger-button"])]
    ui = [(f"{c} vs {bg}", p[c], p[bg]) for c in ("button", "danger-button", "focus", "border-strong")
          for bg in ("bg", "surface")]
    return body, ui


@pytest.mark.parametrize("theme", U.THEMES)
def test_body_text_meets_aa(theme):
    body, _ = pairs(theme)
    bad = [(n, round(ratio(a, b), 2)) for n, a, b in body if ratio(a, b) < 4.5]
    assert not bad, bad


@pytest.mark.parametrize("theme", U.THEMES)
def test_ui_components_and_large_text_meet_3_to_1(theme):
    _, ui = pairs(theme)
    bad = [(n, round(ratio(a, b), 2)) for n, a, b in ui if ratio(a, b) < 3]
    assert not bad, bad


def test_ratio_reference_values():
    assert round(ratio("#000000", "#FFFFFF"), 1) == 21.0 and round(ratio("#777777", "#FFFFFF"), 2) == 4.48
