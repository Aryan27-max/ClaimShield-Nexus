"""Apple-inspired design system: clarity, deference, depth; one accent colour; light and dark themes.
The ONLY place styling lives (with .streamlit/config.toml). Themes are Streamlit's native light / dark themes, chosen
by the visitor's system setting or the sidebar toggle (?theme=…&embed_options=…_theme reloads into that theme), so
dataframes, inputs and menus theme natively. Custom CSS reads (light, dark) tokens through light-dark(), which
resolves against the active theme's color-scheme; Python-side drawing (charts, network, Styler) uses pal()."""
import base64
import functools
import html
import io
import re

import plotly.graph_objects as go
import streamlit as st

from ui.theme import THEMES, chosen_theme, keep_theme_in_url, mode  # noqa: F401  (re-exported for app / pages)

ACCENT, BG, CARD, TEXT, SECONDARY, HAIRLINE = "#0071E3", "#F5F5F7", "#FFFFFF", "#1D1D1F", "#6E6E73", "#E5E5EA"
GREEN, ORANGE, RED, GRAY, LIGHT_GRAY, PURPLE = "#34C759", "#FF9F0A", "#FF3B30", "#8E8E93", "#C7C7CC", "#AF52DE"
FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif'
# (light, dark) design tokens. Semantic fills are Apple system colours; *-text variants are the accessible shades
# used for text (WCAG AA, see tests/test_contrast.py); *-bg are tints for chips, badges and result cards.
TOKENS = {
    "bg": (BG, "#000000"), "surface": (CARD, "#1C1C1E"), "surface-2": ("#F9F9FB", "#2C2C2E"),
    "border": ("#D2D2D7", "#38383A"), "border-strong": ("#86868B", "#8E8E93"), "grid": ("#EDEDF0", "#2C2C2E"),
    "text": (TEXT, "#F5F5F7"), "text-2": (SECONDARY, "#A1A1A6"), "focus": (ACCENT, "#0A84FF"),
    "accent": (ACCENT, "#0A84FF"), "accent-text": ("#0066CC", "#64A8FF"), "accent-bg": ("#E8F2FD", "#0B2A4A"),
    "accent-soft": ("#C9DDF6", "#1E3A5F"), "button": (ACCENT, ACCENT), "danger-button": ("#D70015", "#D70015"),
    "success": (GREEN, "#30D158"), "success-text": ("#1E7B34", "#30D158"), "success-bg": ("#E9F8EE", "#0F2E16"),
    "warning": (ORANGE, "#FFD60A"), "warning-text": ("#A65300", "#FFD60A"), "warning-bg": ("#FFF4E5", "#332A04"),
    "danger": (RED, "#FF453A"), "danger-text": ("#D70015", "#FF6961"), "danger-bg": ("#FFEBEA", "#3B1412"),
    "neutral": (GRAY, "#98989D"), "neutral-text": (SECONDARY, "#A1A1A6"), "neutral-bg": ("#F2F2F7", "#2C2C2E"),
    "sidebar": ("rgba(255,255,255,.72)", "rgba(28,28,30,.72)"), "refers-other": ("#F6C9C5", "#5C2B28"),
    "shadow1": ("rgba(0,0,0,.04)", "rgba(0,0,0,.6)"), "shadow2": ("rgba(0,0,0,.06)", "rgba(0,0,0,.55)"),
}
TONE = {"blue": "accent", "green": "success", "orange": "warning", "red": "danger", "gray": "neutral"}
TONE_NAMES = list(TONE)
LOGOS = {"light": "Black_logo.png", "dark": "White_logo.png"}
PALETTES = {m: {k: v[i] for k, v in TOKENS.items()} | {"logo": LOGOS[m]} for i, m in enumerate(THEMES)}
ACTION_TONES = {"REFER_TO_MFCU": "red", "FULL_INVESTIGATION": "orange", "PREPAY_REVIEW": "blue",
                "PROVIDER_EDUCATION": "green", "NEEDS_MORE_DATA": "gray", "MONITOR": "gray"}
ACTION_COLORS = {"REFER_TO_MFCU": RED, "FULL_INVESTIGATION": ORANGE, "PREPAY_REVIEW": ACCENT,
                 "PROVIDER_EDUCATION": GREEN, "NEEDS_MORE_DATA": GRAY, "MONITOR": LIGHT_GRAY}  # chart fills
ACTION_LABELS = {"REFER_TO_MFCU": "Refer to MFCU", "FULL_INVESTIGATION": "Full investigation",
                 "PREPAY_REVIEW": "Prepay review", "PROVIDER_EDUCATION": "Provider education",
                 "NEEDS_MORE_DATA": "Needs more data", "MONITOR": "Monitor"}
STATUS_TONES = {"in_capacity": "green", "over_capacity": "red", "deferred": "orange", "not_queued": "gray",
                "pending_approval": "blue"}
OBLIGATION_TONES = {"OPEN": "blue", "MET": "green", "OVERDUE": "red"}
STEP_STATES = {"ok": ("green", "✓"), "fail": ("red", "✕"), "pending": ("orange", "pending"), "todo": ("gray", "—"),
               "na": ("gray", "not required"), "revoked": ("red", "revoked")}
CLASS_TONES = {"deterministic": "blue", "structural": "orange", "statistical": "gray", "predictive": "green"}
PALETTE = [ACCENT, ORANGE, GREEN, RED, PURPLE, "#5AC8FA", GRAY]
NODE_COLORS = {"provider": ACCENT, "member": LIGHT_GRAY, "owner": ORANGE, "address": GREEN, "bank": PURPLE,
               "highlight": RED}


def pal(theme: str | None = None) -> dict:
    return PALETTES[theme or mode()]


def tone_text(tone: str, theme: str | None = None) -> str:
    return pal(theme)[f"{TONE.get(tone, 'neutral')}-text"]


def theme_toggle() -> None:
    """Light / Dark segmented control: same-tab links that reload into Streamlit's native theme."""
    cur = mode()
    links = "".join(
        f'<a class="cs-seg{" on" if m == cur else ""}" href="?theme={m}&embed_options={m}_theme" target="_self" '
        f'aria-current="{"true" if m == cur else "false"}" title="Use the {m} theme">'
        f'<span class="cs-ico" aria-hidden="true">{m}_mode</span>{m.capitalize()}</a>' for m in THEMES)
    st.markdown(f'<div class="cs-segbar" role="group" aria-label="Colour theme">{links}</div>', unsafe_allow_html=True)


def pyvis_colors() -> dict:
    p = pal()
    return {"bg": p["surface"], "font": p["text"], "nodes": NODE_COLORS | {"member": p["neutral"]},
            "edges": {"refers": p["danger"], "refers_other": p["refers-other"], "default": p["border"],
                      "owner": p["warning"], "address": p["success"], "bank": PURPLE}}


def pyvis_css() -> str:
    """Network iframe: no loading bar, border in the theme's border colour."""
    return (f"<style>#loadingBar {{ display: none !important; }} #mynetwork {{ border: 1px solid {pal()['border']}"
            f" !important; border-radius: 12px; }} body {{ background: {pal()['surface']}; }}</style>")


def edge_colors() -> dict:
    return pyvis_colors()["edges"]


def var(name: str) -> str:
    return f"var(--cs-{name})"


def css() -> str:
    tokens = "; ".join(f"--cs-{k}: light-dark({lt}, {dk})" for k, (lt, dk) in TOKENS.items())
    v, sh = var, f"0 1px 2px {var('shadow1')}, 0 4px 16px {var('shadow1')}"
    return f"""
<style>
.stApp {{ {tokens}; background: {v("bg")}; }}
html, body, .stApp, button, input, textarea, select, [data-testid="stMarkdownContainer"] {{
  font-family: {FONT}; -webkit-font-smoothing: antialiased; }}
.stApp, [data-testid="stMarkdownContainer"] {{ color: {v("text")}; }}
.block-container {{ padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1280px; }}
h1 {{ font-size: 40px !important; font-weight: 700 !important; letter-spacing: -0.02em; line-height: 1.1; }}
h2, h3 {{ font-weight: 600 !important; letter-spacing: -0.015em; }}
.cs-sub {{ color: {v("text-2")}; font-size: 17px; margin: -0.6rem 0 1.6rem 0; }}
.cs-muted, [data-testid="stCaptionContainer"] {{ color: {v("text-2")} !important; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stAppDeployButton"], [data-testid="stDecoration"] {{
  display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: {v("sidebar")} !important;
  backdrop-filter: saturate(180%) blur(20px); -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-right: 1px solid {v("border")}; }}
[data-testid="stSidebar"] > div {{ background: transparent !important; }}
div[class*="st-key-card_"] {{ background: {v("surface")}; border-radius: 18px; box-shadow: {sh}; padding: 24px;
  transition: box-shadow 150ms ease; }}
div[class*="st-key-card_"]:hover {{ box-shadow: 0 1px 2px {v("shadow2")}, 0 8px 24px {v("shadow2")}; }}
.cs-tile {{ background: {v("surface")}; border-radius: 18px; box-shadow: {sh}; padding: 18px 20px; min-height: 152px;
  transition: transform 150ms ease; }}
.cs-tile:hover {{ transform: translateY(-1px); }}
.cs-tile .l {{ color: {v("text-2")}; font-size: 13px; font-weight: 500; }}
.cs-tile .v {{ color: {v("text")}; font-size: 30px; font-weight: 700; letter-spacing: -0.02em; margin-top: 4px; }}
.cs-tile .d {{ font-size: 13px; margin-top: 2px; color: {v("text-2")}; }}
.cs-tile .v.sm {{ font-size: 22px; line-height: 1.6; letter-spacing: 0; }}
.cs-chip, .cs-badge {{ display: inline-block; padding: 3px 10px; border-radius: 980px; font-size: 12px;
  font-weight: 600; margin: 0 6px 4px 0; letter-spacing: 0; }}
.cs-badge {{ padding: 4px 12px; font-size: 12.5px; }}
.cs-result {{ border-radius: 18px; padding: 20px 24px; font-size: 17px; font-weight: 600; box-shadow: {sh}; }}
.stButton button, .stFormSubmitButton button, .stDownloadButton button {{
  border-radius: 980px !important; background: {v("button")} !important; color: #fff !important;
  border: none !important; font-weight: 500; padding: 0.45rem 1.2rem; transition: filter 150ms ease, transform 150ms; }}
.stButton button:hover, .stFormSubmitButton button:hover {{ filter: brightness(1.08); }}
.stButton button:active, .stFormSubmitButton button:active {{ transform: scale(.98); }}
.stButton button p, .stFormSubmitButton button p, .stDownloadButton button p {{ color: #fff !important; }}
.stButton button:disabled, .stFormSubmitButton button:disabled {{ background: {v("neutral-bg")} !important; }}
.stButton button:disabled p, .stFormSubmitButton button:disabled p {{ color: {v("text-2")} !important; }}
.st-key-verify button, .st-key-verify_sigs button {{ font-size: 19px !important; padding: 0.8rem 2.6rem !important;
  min-height: 3.2rem; }}
button:focus-visible, a:focus-visible, [role="tab"]:focus-visible, input:focus-visible, [tabindex]:focus-visible {{
  outline: 3px solid {v("focus")} !important; outline-offset: 2px !important; }}
.cs-segbar {{ display: inline-flex; gap: 4px; padding: 4px; border-radius: 980px; background: {v("neutral-bg")}; }}
.cs-seg {{ display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: 980px;
  color: {v("text-2")} !important; text-decoration: none !important; font-size: 13px; font-weight: 600; }}
.cs-seg.on {{ background: {v("surface")}; color: {v("text")} !important; box-shadow: {sh}; }}
.cs-ico {{ font-family: "Material Symbols Rounded"; font-size: 18px; line-height: 1; font-weight: 400; }}
[data-testid="stDataFrame"] {{ border: none !important; border-radius: 14px; overflow: hidden; }}
[data-testid="stExpander"] details {{ border: none; background: {v("surface")}; border-radius: 14px;
  box-shadow: {sh}; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 6px; }}
hr {{ border-color: {v("border")} !important; }}
.stPlotlyChart .main-svg text {{ fill: {v("text")} !important; }}
.stPlotlyChart .gridlayer path {{ stroke: {v("grid")} !important; }}
.stPlotlyChart .hoverlayer path {{ fill: {v("surface")} !important; stroke: {v("border")} !important; }}
</style>
"""


def inject_css(root=None) -> None:
    """Design-system CSS (plus the live logo swap while following the system theme) in one element: no layout gap."""
    st.markdown(css() + (logo_css(root) if root and not chosen_theme() else ""), unsafe_allow_html=True)


@functools.lru_cache(maxsize=4)
def _logo_uri(path: str) -> str:
    from PIL import Image
    im = Image.open(path)
    im.thumbnail((128, 128))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def logo(root) -> None:
    """Black logo on the light theme, white logo on the dark theme (public/)."""
    path = str(root / "public" / LOGOS[mode()])
    st.logo(path, size="large", icon_image=path)


def logo_css(root) -> str:
    """Swaps the logo live when the visitor's system theme (which Streamlit follows) changes mid-session."""
    return "<style>" + "".join(f"@media (prefers-color-scheme: {m}) {{ img.stLogo {{ content: url("
                               f"{_logo_uri(str(root / 'public' / f))}); }} }}" for m, f in LOGOS.items()) + "</style>"


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.markdown(f'<div class="cs-sub">{html.escape(subtitle)}</div>', unsafe_allow_html=True)


def card(key: str):
    """Rounded card container (white in light mode, dark grey in dark mode); use as `with card("evidence"):`."""
    return st.container(key=f"card_{key}")


def metric_tile(label: str, value, delta: str | None = None, tone: str | None = None, small: bool = False) -> None:
    """Rounded stat tile; `small` for long values such as hashes or names."""
    color = f' style="color:{var(TONE[tone] + "-text")}"' if tone else ""
    d = f'<div class="d">{html.escape(str(delta))}</div>' if delta else ""
    st.markdown(f'<div class="cs-tile"><div class="l">{html.escape(label)}</div>'
                f'<div class="v{" sm" if small else ""}"{color}>{html.escape(str(value))}</div>{d}</div>',
                unsafe_allow_html=True)


def chip(text: str, tone: str = "gray") -> str:
    t = TONE.get(tone, "neutral")
    return f'<span class="cs-chip" style="color:{var(t + "-text")};background:{var(t + "-bg")}">{html.escape(text)}</span>'


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " ").capitalize())


def action_badge(action: str) -> str:
    """Tinted pill with the action's name (text carries the meaning, colour only reinforces it)."""
    t = TONE[ACTION_TONES.get(action, "gray")]
    return (f'<span class="cs-badge" style="color:{var(t + "-text")};background:{var(t + "-bg")}">'
            f'{html.escape(action_label(action))}</span>')


def class_chips(classes) -> str:
    return "".join(chip(c, CLASS_TONES.get(c, "gray")) for c in classes)


def steps(items: list[tuple[str, str]]) -> str:
    """Authorisation chain as chips joined by arrows, e.g. Policy ✓ → Decision ✓ → Approval pending."""
    out = []
    for label, state in items:
        tone, mark = STEP_STATES.get(state, ("gray", state))
        out.append(chip(f"{label} {mark}", tone))
    return f' <span style="color:{var("text-2")}">→</span> '.join(out)


def html_line(*parts: str) -> None:
    st.markdown(" ".join(parts), unsafe_allow_html=True)


def result_card(ok: bool, text: str) -> None:
    t = "success" if ok else "danger"
    st.markdown(f'<div class="cs-result" role="status" style="color:{var(t + "-text")};background:{var(t + "-bg")}">'
                f'{html.escape(text)}</div>',
                unsafe_allow_html=True)


def table_style(df, action_col: str | None = None, status_col: str | None = None):
    """Pandas Styler colouring action / status text with the theme's accessible text tokens (dataframes are native
    canvases: they can't render HTML badges, and the text label keeps the meaning)."""
    sty = df.style
    acts = {k: tone_text(t) for a, t in ACTION_TONES.items() for k in (a, ACTION_LABELS[a])}
    stats = {k: tone_text(t) for s, t in STATUS_TONES.items() for k in (s, s.replace("_", " "))}
    if action_col:
        sty = sty.map(lambda v: f"color:{acts[v]};font-weight:600" if v in acts else "", subset=[action_col])
    if status_col:
        sty = sty.map(lambda v: f"color:{stats[v]};font-weight:500" if v in stats else "", subset=[status_col])
    return sty


def plot(fig: go.Figure, container=None) -> None:
    """Plotly chart in this design system. Transparent backgrounds set on the figure itself (Streamlit injects its
    page background unless the layout defines one), so the themed card shows through in light and dark mode."""
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    (container or st).plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False, "responsive": True})


def plotly_template(theme: str | None = None) -> go.layout.Template:
    p = pal(theme)
    return go.layout.Template(layout=dict(
        font=dict(family=FONT, color=p["text"], size=13), colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",  # the themed card shows through
        xaxis=dict(showgrid=False, zeroline=False, linecolor=p["border"], ticks="", automargin=True),
        yaxis=dict(showgrid=True, gridcolor=p["grid"], zeroline=False, ticks="", automargin=True),
        legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=8, t=24, b=8), hoverlabel=dict(font=dict(family=FONT), bgcolor=p["surface"])))


def legend(colors: dict[str, str]) -> str:
    """Inline legend of coloured dots, e.g. node types on the network page."""
    return " ".join(f'<span class="cs-chip" style="color:{var("text")};background:{var("neutral-bg")}">'
                    f'<span style="color:{c}">●</span> {html.escape(k)}</span>' for k, c in colors.items())
