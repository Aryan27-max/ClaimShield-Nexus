import tomllib

from core import schema as S
from ui import export
from ui import style as U


def test_palettes_cover_the_same_tokens():
    light, dark = U.PALETTES["light"], U.PALETTES["dark"]
    assert set(light) == set(dark) == set(U.TOKENS) | {"logo"}
    assert light["bg"] != dark["bg"] and light["text"] != dark["text"] and light["card"] != dark["card"]
    assert all(f"{t}-fg" in U.TOKENS and f"{t}-bg" in U.TOKENS for t in U.TONE_NAMES)


def test_css_switches_live_with_the_streamlit_theme():
    css = U.css()
    assert "--cs-card: light-dark(#FFFFFF, #1C1C1E)" in css and "--cs-bg: light-dark(#F5F5F7, #000000)" in css
    assert "background: var(--cs-card)" in css
    assert "var(--cs-red-fg)" in U.chip("x", "red") and "var(--cs-gray-bg)" in U.chip("x", "nope")


def test_logo_per_theme_exists():
    assert U.PALETTES["light"]["logo"] == "Black_logo.png" and U.PALETTES["dark"]["logo"] == "White_logo.png"
    for p in U.PALETTES.values():
        assert (S.ROOT / "public" / p["logo"]).exists()


def test_defaults_to_light_without_a_browser():
    assert U.mode() == "light" and U.pal() is U.PALETTES["light"]
    assert U.edge_colors()["default"] == U.PALETTES["light"]["hairline"]


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
