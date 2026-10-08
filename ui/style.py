"""Apple-inspired design system: clarity, deference, depth; one accent colour; light and dark mode.
The ONLY place styling lives. Streamlit follows the visitor's system theme; custom CSS reads (light, dark) tokens
through light-dark(), so it switches live with Streamlit's color-scheme. Semantic colours work on both backgrounds."""
import base64
import functools
import html
import io
import re

import plotly.graph_objects as go
import streamlit as st

ACCENT, BG, CARD, TEXT, SECONDARY, HAIRLINE = "#0071E3", "#F5F5F7", "#FFFFFF", "#1D1D1F", "#6E6E73", "#E5E5EA"
GREEN, ORANGE, RED, GRAY, LIGHT_GRAY, PURPLE = "#34C759", "#FF9F0A", "#FF3B30", "#8E8E93", "#C7C7CC", "#AF52DE"
FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif'
# (light, dark) colour tokens. CSS uses them through light-dark() so custom components follow the active Streamlit
# theme instantly; Python-side drawing (logo file, chart text, network graph) uses the palette of the current run.
TOKENS = {"bg": (BG, "#000000"), "card": (CARD, "#1C1C1E"), "text": (TEXT, "#F5F5F7"), "secondary": (SECONDARY, "#98989D"),
          "hairline": (HAIRLINE, "#38383A"), "grid": ("#EDEDF0", "#2C2C2E"), "accent": (ACCENT, "#0A84FF"),
          "accent_soft": ("#C9DDF6", "#1E3A5F"), "sidebar": ("rgba(255,255,255,.72)", "rgba(28,28,30,.72)"),
          "refers_other": ("#F6C9C5", "#5C2B28"), "shadow1": ("rgba(0,0,0,.04)", "rgba(0,0,0,.6)"),
          "shadow2": ("rgba(0,0,0,.06)", "rgba(0,0,0,.55)"),
          "blue-fg": (ACCENT, "#64A8FF"), "blue-bg": ("#E8F2FD", "#0B2A4A"), "green-fg": ("#248A3D", "#32D74B"),
          "green-bg": ("#E9F8EE", "#0F2E16"), "orange-fg": ("#C93400", "#FFB340"), "orange-bg": ("#FFF4E5", "#3A2606"),
          "red-fg": ("#D70015", "#FF6961"), "red-bg": ("#FFEBEA", "#3B1412"), "gray-fg": (SECONDARY, "#AEAEB2"),
          "gray-bg": ("#F2F2F7", "#2C2C2E")}
LOGOS = {"light": "Black_logo.png", "dark": "White_logo.png"}
PALETTES = {m: {k: v[i] for k, v in TOKENS.items()} | {"logo": LOGOS[m]} for i, m in enumerate(("light", "dark"))}
TONE_NAMES = ["blue", "green", "orange", "red", "gray"]
ACTION_COLORS = {"REFER_TO_MFCU": RED, "FULL_INVESTIGATION": ORANGE, "PREPAY_REVIEW": ACCENT,
                 "PROVIDER_EDUCATION": GREEN, "NEEDS_MORE_DATA": GRAY, "MONITOR": LIGHT_GRAY}
ACTION_LABELS = {"REFER_TO_MFCU": "Refer to MFCU", "FULL_INVESTIGATION": "Full investigation",
                 "PREPAY_REVIEW": "Prepay review", "PROVIDER_EDUCATION": "Provider education",
                 "NEEDS_MORE_DATA": "Needs more data", "MONITOR": "Monitor"}
STATUS_COLORS = {"in_capacity": GREEN, "over_capacity": RED, "deferred": ORANGE, "not_queued": GRAY,
                 "pending_approval": PURPLE}
OBLIGATION_TONES = {"OPEN": "blue", "MET": "green", "OVERDUE": "red"}
STEP_STATES = {"ok": ("green", "✓"), "fail": ("red", "✕"), "pending": ("orange", "pending"), "todo": ("gray", "—"),
               "na": ("gray", "not required"), "revoked": ("red", "revoked")}
CLASS_TONES = {"deterministic": "blue", "structural": "orange", "statistical": "gray", "predictive": "green"}
PALETTE = [ACCENT, ORANGE, GREEN, RED, PURPLE, "#5AC8FA", GRAY]
NODE_COLORS = {"provider": ACCENT, "member": LIGHT_GRAY, "owner": ORANGE, "address": GREEN, "bank": PURPLE,
               "highlight": RED}


def pyvis_css() -> str:
    """Network iframe: no loading bar, border in the theme's hairline colour."""
    return (f"<style>#loadingBar {{ display: none !important; }} #mynetwork {{ border: 1px solid {pal()['hairline']}"
            f" !important; }}</style>")


def mode() -> str:
    """Active theme of this session ("light" or "dark"); light when unknown (tests, first paint)."""
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # no browser context
        return "light"


def pal() -> dict:
    return PALETTES[mode()]


def edge_colors() -> dict:
    p = pal()
    return {"refers": RED, "refers_other": p["refers_other"], "default": p["hairline"], "owner": ORANGE,
            "address": GREEN, "bank": PURPLE}


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
.cs-sub {{ color: {v("secondary")}; font-size: 17px; margin: -0.6rem 0 1.6rem 0; }}
.cs-muted, [data-testid="stCaptionContainer"] {{ color: {v("secondary")} !important; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stAppDeployButton"], [data-testid="stDecoration"] {{
  display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: {v("sidebar")} !important;
  backdrop-filter: saturate(180%) blur(20px); -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-right: 1px solid {v("hairline")}; }}
[data-testid="stSidebar"] > div {{ background: transparent !important; }}
div[class*="st-key-card_"] {{ background: {v("card")}; border-radius: 18px; box-shadow: {sh}; padding: 24px;
  transition: box-shadow 150ms ease; }}
div[class*="st-key-card_"]:hover {{ box-shadow: 0 1px 2px {v("shadow2")}, 0 8px 24px {v("shadow2")}; }}
.cs-tile {{ background: {v("card")}; border-radius: 18px; box-shadow: {sh}; padding: 18px 20px; min-height: 152px;
  transition: transform 150ms ease; }}
.cs-tile:hover {{ transform: translateY(-1px); }}
.cs-tile .l {{ color: {v("secondary")}; font-size: 13px; font-weight: 500; }}
.cs-tile .v {{ color: {v("text")}; font-size: 30px; font-weight: 700; letter-spacing: -0.02em; margin-top: 4px; }}
.cs-tile .d {{ font-size: 13px; margin-top: 2px; color: {v("secondary")}; }}
.cs-tile .v.sm {{ font-size: 22px; line-height: 1.6; letter-spacing: 0; }}
.cs-chip {{ display: inline-block; padding: 3px 10px; border-radius: 980px; font-size: 12px; font-weight: 600;
  margin: 0 6px 4px 0; letter-spacing: 0; }}
.cs-badge {{ display: inline-block; padding: 4px 12px; border-radius: 980px; font-size: 12px; font-weight: 600;
  color: #fff; letter-spacing: .01em; }}
.cs-result {{ border-radius: 18px; padding: 20px 24px; font-size: 17px; font-weight: 600; box-shadow: {sh}; }}
.stButton button, .stFormSubmitButton button, .stDownloadButton button {{
  border-radius: 980px !important; background: {v("accent")} !important; color: #fff !important;
  border: none !important; font-weight: 500; padding: 0.45rem 1.2rem; transition: filter 150ms ease, transform 150ms; }}
.stButton button:hover, .stFormSubmitButton button:hover {{ filter: brightness(1.08); }}
.stButton button:active, .stFormSubmitButton button:active {{ transform: scale(.98); }}
.stButton button p, .stFormSubmitButton button p, .stDownloadButton button p {{ color: #fff !important; }}
.stButton button:disabled, .stFormSubmitButton button:disabled {{ background: {v("hairline")} !important; }}
.stButton button:disabled p, .stFormSubmitButton button:disabled p {{ color: {GRAY} !important; }}
.st-key-verify button, .st-key-verify_sigs button {{ font-size: 19px !important; padding: 0.8rem 2.6rem !important;
  min-height: 3.2rem; }}
[data-testid="stDataFrame"] {{ border: none !important; border-radius: 14px; overflow: hidden; }}
[data-testid="stExpander"] details {{ border: none; background: {v("card")}; border-radius: 14px; box-shadow: {sh}; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 6px; }}
hr {{ border-color: {v("hairline")} !important; }}
.stPlotlyChart .main-svg text {{ fill: {v("text")} !important; }}
.stPlotlyChart .gridlayer path {{ stroke: {v("grid")} !important; }}
.stPlotlyChart .hoverlayer path {{ fill: {v("card")} !important; stroke: {v("hairline")} !important; }}
</style>
"""


def inject_css(root=None) -> None:
    """Design-system CSS plus the live logo swap, in one element so it adds no layout gap."""
    st.markdown(css() + (logo_css(root) if root else ""), unsafe_allow_html=True)


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
    color = f' style="color:{var(tone + "-fg")}"' if tone else ""
    d = f'<div class="d">{html.escape(str(delta))}</div>' if delta else ""
    st.markdown(f'<div class="cs-tile"><div class="l">{html.escape(label)}</div>'
                f'<div class="v{" sm" if small else ""}"{color}>{html.escape(str(value))}</div>{d}</div>',
                unsafe_allow_html=True)


def chip(text: str, tone: str = "gray") -> str:
    tone = tone if tone in TONE_NAMES else "gray"
    return f'<span class="cs-chip" style="color:{var(tone + "-fg")};background:{var(tone + "-bg")}">{html.escape(text)}</span>'


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " ").capitalize())


def action_badge(action: str) -> str:
    c = ACTION_COLORS.get(action, GRAY)
    fg = TEXT if action == "MONITOR" else "#fff"
    return f'<span class="cs-badge" style="background:{c};color:{fg}">{action_label(action)}</span>'


def class_chips(classes) -> str:
    return "".join(chip(c, CLASS_TONES.get(c, "gray")) for c in classes)


def steps(items: list[tuple[str, str]]) -> str:
    """Authorisation chain as chips joined by arrows, e.g. Policy ✓ → Decision ✓ → Approval pending."""
    out = []
    for label, state in items:
        tone, mark = STEP_STATES.get(state, ("gray", state))
        out.append(chip(f"{label} {mark}", tone))
    return f' <span style="color:{var("secondary")}">→</span> '.join(out)


def html_line(*parts: str) -> None:
    st.markdown(" ".join(parts), unsafe_allow_html=True)


def result_card(ok: bool, text: str) -> None:
    t = "green" if ok else "red"
    st.markdown(f'<div class="cs-result" style="color:{var(t + "-fg")};background:{var(t + "-bg")}">'
                f'{html.escape(text)}</div>',
                unsafe_allow_html=True)


def table_style(df, action_col: str | None = None, status_col: str | None = None):
    """Pandas Styler colouring action / status text (dataframes can't render HTML badges)."""
    sty = df.style
    acts = {**ACTION_COLORS, **{ACTION_LABELS[a]: c for a, c in ACTION_COLORS.items()}}
    stats = {**STATUS_COLORS, **{s.replace("_", " "): c for s, c in STATUS_COLORS.items()}}
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


def plotly_template() -> go.layout.Template:
    p = pal()
    return go.layout.Template(layout=dict(
        font=dict(family=FONT, color=p["text"], size=13), colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",  # the themed card shows through
        xaxis=dict(showgrid=False, zeroline=False, linecolor=p["hairline"], ticks="", automargin=True),
        yaxis=dict(showgrid=True, gridcolor=p["grid"], zeroline=False, ticks="", automargin=True),
        legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=8, t=24, b=8), hoverlabel=dict(font=dict(family=FONT), bgcolor=p["card"])))


def legend(colors: dict[str, str]) -> str:
    """Inline legend of coloured dots, e.g. node types on the network page."""
    return " ".join(f'<span class="cs-chip" style="color:{var("text")};background:{var("gray-bg")}">'
                    f'<span style="color:{c}">●</span> {html.escape(k)}</span>' for k, c in colors.items())
