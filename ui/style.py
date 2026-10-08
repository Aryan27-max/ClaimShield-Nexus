"""Apple-inspired design system: clarity, deference, depth; one accent colour; light mode only.
The ONLY place styling lives."""
import html
import re

import plotly.graph_objects as go
import streamlit as st

ACCENT, BG, CARD, TEXT, SECONDARY, HAIRLINE = "#0071E3", "#F5F5F7", "#FFFFFF", "#1D1D1F", "#6E6E73", "#E5E5EA"
GREEN, ORANGE, RED, GRAY, LIGHT_GRAY = "#34C759", "#FF9F0A", "#FF3B30", "#8E8E93", "#C7C7CC"
ACCENT_SOFT = "#C9DDF6"
FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif'
ACTION_COLORS = {"REFER_TO_MFCU": RED, "FULL_INVESTIGATION": ORANGE, "PREPAY_REVIEW": ACCENT,
                 "PROVIDER_EDUCATION": GREEN, "NEEDS_MORE_DATA": GRAY, "MONITOR": LIGHT_GRAY}
STATUS_COLORS = {"in_capacity": GREEN, "over_capacity": RED, "deferred": ORANGE, "not_queued": GRAY}
TONES = {"blue": (ACCENT, "#E8F2FD"), "green": ("#248A3D", "#E9F8EE"), "orange": ("#C93400", "#FFF4E5"),
         "red": ("#D70015", "#FFEBEA"), "gray": (SECONDARY, "#F2F2F7")}
CLASS_TONES = {"deterministic": "blue", "structural": "orange", "statistical": "gray", "predictive": "green"}
PALETTE = [ACCENT, ORANGE, GREEN, RED, "#AF52DE", "#5AC8FA", GRAY]
NODE_COLORS = {"provider": ACCENT, "member": LIGHT_GRAY, "owner": ORANGE, "address": GREEN, "bank": "#AF52DE",
               "highlight": RED}
EDGE_COLORS = {"refers": RED, "default": HAIRLINE}
SHADOW = "0 1px 2px rgba(0,0,0,.04), 0 4px 16px rgba(0,0,0,.04)"

CSS = f"""
<style>
html, body, .stApp, button, input, textarea, select, [data-testid="stMarkdownContainer"] {{
  font-family: {FONT}; -webkit-font-smoothing: antialiased; color: {TEXT}; }}
.stApp {{ background: {BG}; }}
.block-container {{ padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1280px; }}
h1 {{ font-size: 40px !important; font-weight: 700 !important; letter-spacing: -0.02em; line-height: 1.1; }}
h2, h3 {{ font-weight: 600 !important; letter-spacing: -0.015em; }}
.cs-sub {{ color: {SECONDARY}; font-size: 17px; margin: -0.6rem 0 1.6rem 0; }}
.cs-muted, [data-testid="stCaptionContainer"] {{ color: {SECONDARY} !important; }}
#MainMenu, footer, [data-testid="stToolbar"], [data-testid="stAppDeployButton"], [data-testid="stDecoration"] {{
  display: none !important; }}
header[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background: rgba(255,255,255,.72) !important;
  backdrop-filter: saturate(180%) blur(20px); -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-right: 1px solid {HAIRLINE}; }}
[data-testid="stSidebar"] > div {{ background: transparent !important; }}
div[class*="st-key-card_"] {{ background: {CARD}; border-radius: 18px; box-shadow: {SHADOW}; padding: 24px;
  transition: box-shadow 150ms ease; }}
div[class*="st-key-card_"]:hover {{ box-shadow: 0 1px 2px rgba(0,0,0,.05), 0 8px 24px rgba(0,0,0,.06); }}
.cs-tile {{ background: {CARD}; border-radius: 18px; box-shadow: {SHADOW}; padding: 18px 20px; min-height: 104px;
  transition: transform 150ms ease; }}
.cs-tile:hover {{ transform: translateY(-1px); }}
.cs-tile .l {{ color: {SECONDARY}; font-size: 13px; font-weight: 500; }}
.cs-tile .v {{ font-size: 30px; font-weight: 700; letter-spacing: -0.02em; margin-top: 4px; }}
.cs-tile .d {{ font-size: 13px; margin-top: 2px; color: {SECONDARY}; }}
.cs-chip {{ display: inline-block; padding: 3px 10px; border-radius: 980px; font-size: 12px; font-weight: 600;
  margin: 0 6px 4px 0; letter-spacing: 0; }}
.cs-badge {{ display: inline-block; padding: 4px 12px; border-radius: 980px; font-size: 12px; font-weight: 600;
  color: #fff; letter-spacing: .01em; }}
.cs-result {{ border-radius: 18px; padding: 20px 24px; font-size: 17px; font-weight: 600; box-shadow: {SHADOW}; }}
.stButton button, .stFormSubmitButton button, .stDownloadButton button {{
  border-radius: 980px !important; background: {ACCENT} !important; color: #fff !important; border: none !important;
  font-weight: 500; padding: 0.45rem 1.2rem; transition: filter 150ms ease, transform 150ms ease; }}
.stButton button:hover, .stFormSubmitButton button:hover {{ filter: brightness(1.08); }}
.stButton button:active, .stFormSubmitButton button:active {{ transform: scale(.98); }}
.stButton button:disabled {{ background: {LIGHT_GRAY} !important; }}
.st-key-verify button {{ font-size: 19px !important; padding: 0.8rem 2.6rem !important; min-height: 3.2rem; }}
[data-testid="stDataFrame"] {{ border: none !important; border-radius: 14px; overflow: hidden; }}
[data-testid="stExpander"] details {{ border: none; background: {CARD}; border-radius: 14px; box-shadow: {SHADOW}; }}
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 6px; }}
[data-testid="stTabs"] button[role="tab"] {{ border-radius: 980px; padding: 6px 16px; transition: background 150ms; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"], [data-testid="stTabs"] [data-baseweb="tab-border"] {{
  display: none; }}
[data-testid="stTabs"] button[aria-selected="true"] {{ background: {CARD}; box-shadow: {SHADOW}; }}
hr {{ border-color: {HAIRLINE} !important; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.markdown(f'<div class="cs-sub">{subtitle}</div>', unsafe_allow_html=True)


def card(key: str):
    """White rounded container; use as `with card("evidence"):`."""
    return st.container(key=f"card_{key}")


def metric_tile(label: str, value, delta: str | None = None, tone: str | None = None) -> None:
    color = TONES[tone][0] if tone else TEXT
    d = f'<div class="d">{html.escape(str(delta))}</div>' if delta else ""
    st.markdown(f'<div class="cs-tile"><div class="l">{html.escape(label)}</div>'
                f'<div class="v" style="color:{color}">{html.escape(str(value))}</div>{d}</div>',
                unsafe_allow_html=True)


def chip(text: str, tone: str = "gray") -> str:
    fg, bg = TONES.get(tone, TONES["gray"])
    return f'<span class="cs-chip" style="color:{fg};background:{bg}">{html.escape(text)}</span>'


def action_badge(action: str) -> str:
    c = ACTION_COLORS.get(action, GRAY)
    fg = TEXT if action == "MONITOR" else "#fff"
    return f'<span class="cs-badge" style="background:{c};color:{fg}">{action.replace("_", " ").title()}</span>'


def class_chips(classes) -> str:
    return "".join(chip(c, CLASS_TONES.get(c, "gray")) for c in classes)


def html_line(*parts: str) -> None:
    st.markdown(" ".join(parts), unsafe_allow_html=True)


def result_card(ok: bool, text: str) -> None:
    fg, bg = TONES["green" if ok else "red"]
    st.markdown(f'<div class="cs-result" style="color:{fg};background:{bg}">{html.escape(text)}</div>',
                unsafe_allow_html=True)


def table_style(df, action_col: str | None = None, status_col: str | None = None):
    """Pandas Styler colouring action / status text (dataframes can't render HTML badges)."""
    sty = df.style
    if action_col:
        sty = sty.map(lambda v: f"color:{ACTION_COLORS.get(v, TEXT)};font-weight:600", subset=[action_col])
    if status_col:
        sty = sty.map(lambda v: f"color:{STATUS_COLORS.get(v, TEXT)};font-weight:500", subset=[status_col])
    return sty


def plotly_template() -> go.layout.Template:
    return go.layout.Template(layout=dict(
        font=dict(family=FONT, color=TEXT, size=13), colorway=PALETTE,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False, linecolor=HAIRLINE, ticks=""),
        yaxis=dict(showgrid=True, gridcolor="#EDEDF0", zeroline=False, ticks=""),
        legend=dict(orientation="h", y=1.12, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=8, r=8, t=24, b=8), hoverlabel=dict(font=dict(family=FONT), bgcolor=CARD)))


def legend(colors: dict[str, str]) -> str:
    """Inline legend of coloured dots, e.g. node types on the network page."""
    return " ".join(f'<span class="cs-chip" style="color:{TEXT};background:{TONES["gray"][1]}">'
                    f'<span style="color:{c}">●</span> {html.escape(k)}</span>' for k, c in colors.items())


PRINT_CSS = f"""body {{ font-family: {FONT}; color: {TEXT}; max-width: 900px; margin: 40px auto; padding: 0 24px;
  line-height: 1.45; font-size: 14px; }}
h1 {{ font-size: 28px; letter-spacing: -0.02em; }} h2 {{ font-size: 19px; margin-top: 28px;
  border-bottom: 1px solid {HAIRLINE}; padding-bottom: 4px; }} h3 {{ font-size: 15px; color: {SECONDARY}; }}
table {{ border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12px; }}
th, td {{ border: 1px solid {HAIRLINE}; padding: 4px 8px; text-align: left; vertical-align: top; }}
th {{ background: {BG}; }} pre {{ background: {BG}; padding: 10px; border-radius: 8px; white-space: pre-wrap;
  font-size: 12px; }} @media print {{ body {{ margin: 0; }} h2 {{ break-after: avoid; }} tr {{ break-inside: avoid; }} }}"""


def _inline(s: str) -> str:
    s = html.escape(s).replace("\\|", "|")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def print_html(md: str, title: str) -> str:
    """Print-friendly standalone HTML from the brief's markdown subset (headings, tables, lists, code, bold)."""
    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = lines.index("```", i + 1) if "```" in lines[i + 1:] else len(lines)
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").replace("\\|", "\0").split("|")])
                i += 1
            cell = lambda c, t: f"<{t}>{_inline(c.replace(chr(0), chr(92) + '|'))}</{t}>"  # noqa: E731
            body = "".join("<tr>" + "".join(cell(c, "td") for c in r) + "</tr>" for r in rows[2:])
            out.append("<table><tr>" + "".join(cell(c, "th") for c in rows[0]) + "</tr>" + body + "</table>")
            continue
        for p, tag in (("### ", "h3"), ("## ", "h2"), ("# ", "h1")):
            if ln.startswith(p):
                out.append(f"<{tag}>{_inline(ln[len(p):])}</{tag}>")
                break
        else:
            if ln.startswith("- "):
                out.append(f"<div>• {_inline(ln[2:])}</div>")
            elif ln.strip():
                out.append(f"<p>{_inline(ln)}</p>")
        i += 1
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{PRINT_CSS}</style></head><body>{''.join(out)}</body></html>")
