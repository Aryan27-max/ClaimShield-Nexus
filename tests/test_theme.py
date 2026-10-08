import tomllib

from core import schema as S
from ui import export
from ui import style as U


def test_palettes_cover_the_same_tokens():
    light, dark = U.PALETTES["light"], U.PALETTES["dark"]
    assert set(light) == set(dark) == set(U.TOKENS) | {"logo"}
    assert light["bg"] != dark["bg"] and light["text"] != dark["text"] and light["surface"] != dark["surface"]
    assert all(f"{U.TONE[t]}-text" in U.TOKENS and f"{U.TONE[t]}-bg" in U.TOKENS for t in U.TONE_NAMES)
    assert light["accent"] == "#0071E3" and dark["accent"] == "#0A84FF"
    assert (light["success"], light["warning"], light["danger"], light["neutral"]) == ("#34C759", "#FF9F0A", "#FF3B30",
                                                                                     "#8E8E93")
    assert (dark["success"], dark["warning"], dark["danger"], dark["neutral"]) == ("#30D158", "#FFD60A", "#FF453A",
                                                                                 "#98989D")
    assert dark["text"] == "#F5F5F7" and dark["text-2"] == "#A1A1A6"


def test_css_switches_live_with_the_streamlit_theme():
    css = U.css()
    assert "--cs-surface: light-dark(#FFFFFF, #1C1C1E)" in css and "--cs-bg: light-dark(#F5F5F7, #000000)" in css
    assert "background: var(--cs-surface)" in css and ":focus-visible" in css
    assert "var(--cs-danger-text)" in U.chip("x", "red") and "var(--cs-neutral-bg)" in U.chip("x", "nope")
    assert "var(--cs-danger-text)" in U.action_badge("REFER_TO_MFCU") and "Refer to MFCU" in U.action_badge("REFER_TO_MFCU")


def test_logo_per_theme_exists():
    assert U.PALETTES["light"]["logo"] == "Black_logo.png" and U.PALETTES["dark"]["logo"] == "White_logo.png"
    for p in U.PALETTES.values():
        assert (S.ROOT / "public" / p["logo"]).exists()


def test_defaults_to_light_without_a_browser():
    assert U.mode() == "light" and U.pal() is U.PALETTES["light"]
    assert U.edge_colors()["default"] == U.PALETTES["light"]["border"]
    assert U.plotly_template("dark").layout.font.color == "#F5F5F7"


def test_streamlit_config_defines_both_themes():
    cfg = tomllib.loads((S.ROOT / ".streamlit" / "config.toml").read_text())
    assert {"light", "dark"} <= set(cfg["theme"]) and "base" not in cfg["theme"]


def test_print_export_stays_light():
    html = export.print_html("# Brief\n\n| a | b |\n|---|---|\n| 1 | 2 |", "t")
    assert U.TEXT in html and "<table>" in html


def test_logo_swaps_live_with_the_system_theme():
    css = U.logo_css(S.ROOT)
    assert "@media (prefers-color-scheme: dark)" in css and "@media (prefers-color-scheme: light)" in css
    assert css.count("data:image/png;base64,") == 2 and len(css) < 60_000
