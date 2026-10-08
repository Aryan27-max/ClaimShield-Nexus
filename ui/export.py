"""Print-friendly HTML export of investigation briefs (always light, for paper / PDF), using the design-system fonts
and neutrals from ui/style.py."""
import html
import re

from ui.style import BG, FONT, HAIRLINE, SECONDARY, TEXT

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
