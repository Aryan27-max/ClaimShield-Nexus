"""Shared, cached loaders and helpers for the Streamlit pages. Slider changes re-rank only; no pipeline rerun."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import networkx as nx  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from core import graph, harness, identity, phi  # noqa: E402
from core import queue as Q  # noqa: E402
from core import schema as S  # noqa: E402
from ui import style as U  # noqa: E402

PYVIS_OPTIONS = ('{"physics": {"enabled": true, "solver": "barnesHut", "stabilization": {"enabled": true, '
                 '"iterations": 100, "updateInterval": 50, "fit": true}}, "interaction": {"hover": true}}')
FREEZE_JS = ' network.once("stabilizationIterationsDone", function () { network.setOptions({physics: false}); });'
FOOTER = "Recommendation only — final action requires a human decision."


def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def policy_files() -> list[str]:
    return sorted(str(p) for p in (ROOT / "policy").glob("harness_v*.yaml"))


@st.cache_data(show_spinner=False)
def _policy(path: str, mtime: float) -> dict:
    return harness.load_policy(path)


def policy(path: str | None = None) -> dict:
    path = path or st.session_state.get("policy_path") or str(S.POLICY)
    return _policy(path, _mtime(Path(path)))


def policy_label(path: str) -> str:
    try:
        p = policy(path)
        return f"v{p['version']} · {Path(path).stem} · {p['_hash'][:10]}"
    except (OSError, ValueError):
        return f"{Path(path).stem} · invalid"


@st.cache_data(show_spinner=False)
def _cases(path: str, mtime: float, cases_mtime: float) -> pd.DataFrame:
    base = pd.read_parquet(S.CASES).drop(columns=harness.OUTPUT_COLS, errors="ignore")
    return harness.evaluate_all(base, harness.load_policy(path))


def cases() -> pd.DataFrame:
    """Fused cases re-evaluated under the selected policy (cheap; cached per policy file version)."""
    pol = policy()
    return _cases(pol["_path"], _mtime(Path(pol["_path"])), _mtime(S.CASES))


@st.cache_data(show_spinner=False)
def _ranked(path: str, mtime: float, cases_mtime: float, investigators: int, horizon: int) -> pd.DataFrame:
    q = Q.rank(_cases(path, mtime, cases_mtime), harness.load_policy(path), investigators=investigators, horizon=horizon)
    return q


def me() -> str:
    """Signed-in demo identity from the sidebar (an investigator by default)."""
    return str(st.session_state.get("identity") or "inv.a")


def my_role() -> str | None:
    return identity.role(me())


def investigators() -> int:
    """Sidebar value, else the policy default (pages can render before the sidebar, e.g. in tests)."""
    return int(st.session_state.get("investigators") or policy()["capacity"]["investigators"])


def horizon() -> int:
    return int(st.session_state.get("horizon") or 90)


def ranked() -> pd.DataFrame:
    pol = policy()
    return _ranked(pol["_path"], _mtime(Path(pol["_path"])), _mtime(S.CASES), investigators(), horizon())


def require_cases(q: pd.DataFrame) -> None:
    """Friendly empty state instead of index errors when the data yields no cases."""
    if q.empty:
        st.info("No cases under this data and policy: nothing needs investigator attention right now. "
                "Re-run the pipeline when new claims arrive.")
        st.caption(FOOTER)
        st.stop()


def show_error(e: Exception, what: str) -> None:
    """Plain-language error with the technical details folded away."""
    st.error(f"{what}: {e}")
    with st.expander("Technical details"):
        st.exception(e)


@st.cache_data(show_spinner=False)
def run_meta(mtime: float | None = None) -> dict:
    return json.loads(S.RUN_META.read_text()) if S.RUN_META.exists() else {}


def meta() -> dict:
    return run_meta(_mtime(S.RUN_META))


@st.cache_data(show_spinner=False)
def claims(mtime: float) -> pd.DataFrame:
    c = S.load("claims")[["claim_id", "provider_id", "member_id", "service_date", "cpt", "paid_amt"]]
    return c.astype({"claim_id": str, "provider_id": str, "member_id": str, "cpt": str})


@st.cache_resource(show_spinner=False)
def graph_obj(mtime: float) -> tuple[nx.Graph, pd.DataFrame]:
    G = graph.build_graph(*(S.load(n) for n in ["providers", "referrals", "claims"]))
    return G, S.load("graph_features")


def ego_html(entity_id: str, highlight: list[str], max_nodes: int = 150) -> tuple[str, int]:
    from pyvis.network import Network
    G, gf = graph_obj(_mtime(S.OUT / "claims.parquet"))
    sub = graph.ego_graph(entity_id, max_nodes=max_nodes, G=G, graph_features=gf)
    pc = U.pyvis_colors()
    net = Network(height="520px", width="100%", cdn_resources="in_line", bgcolor=pc["bg"], font_color=pc["font"])
    for n, d in sub.nodes(data=True):
        kind = d.get("kind", "?")
        hot = n in highlight
        net.add_node(n, label=n if kind != "member" else "",
                     title=f"{kind} {phi.token(n) if kind == 'member' else n} {d.get('type', '')}",
                     color=pc["nodes"]["highlight"] if hot else pc["nodes"].get(kind, U.GRAY),
                     size=22 if hot else (8 if kind == "member" else 14))
    hl, edges = set(highlight), pc["edges"]
    for u, v, d in sub.edges(data=True):
        rel, inner, touches = d.get("rel", ""), u in hl and v in hl, u in hl or v in hl
        if rel == "refers":
            color, width = (edges["refers"], 3) if inner else (edges["refers_other"], 1)
        elif rel in ("owner", "address", "bank") and touches:
            color, width = edges[rel], 2
        else:
            color, width = edges["default"], 1
        net.add_edge(u, v, title=rel, color=color, width=width)
    net.set_options(PYVIS_OPTIONS)
    html = net.generate_html().replace("network = new vis.Network(container, data, options);",
                                       "network = new vis.Network(container, data, options);" + FREEZE_JS)
    return html.replace("</head>", U.pyvis_css() + "</head>", 1), sub.number_of_nodes()


@st.cache_data(show_spinner=False)
def _table(name: str, mtime: float) -> pd.DataFrame:
    return S.load(name)


def table(name: str) -> pd.DataFrame:
    """Any data/out table, cached per file version."""
    return _table(name, _mtime(S.OUT / f"{name}.parquet"))


@st.cache_data(show_spinner=False)
def _flows(mtime: float) -> pd.DataFrame:
    c = S.load("claims")[["referring_provider_id", "provider_id"]].dropna().astype(str)
    return c.groupby(["referring_provider_id", "provider_id"]).size().rename("n").reset_index()


def referral_flows() -> pd.DataFrame:
    """Referred claims per (referring provider, billing provider)."""
    return _flows(_mtime(S.OUT / "claims.parquet"))


@st.cache_data(show_spinner=False)
def _labels(mtime: float) -> pd.DataFrame:
    from eval.metrics import entity_labels
    return entity_labels()


def has_ground_truth() -> bool:
    return all((S.OUT / f"{n}.parquet").exists() for n in ("ground_truth", "legit_outliers"))


def labels() -> pd.DataFrame:
    """Ground-truth entity labels: for the synthetic-validation sections only (never fed to core)."""
    return _labels(_mtime(S.OUT / "ground_truth.parquet"))
