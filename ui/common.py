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

from core import graph, harness  # noqa: E402
from core import queue as Q  # noqa: E402
from core import schema as S  # noqa: E402

HARNESS_COLS = ["allowed_actions", "recommended_action", "rule_trace", "requires_human", "missing_classes",
                "est_hours", "policy_version", "policy_hash"]
FOOTER = "Recommendation only — final action requires a human decision."
KIND_COLOR = {"provider": "#4C78A8", "member": "#BAB0AC", "owner": "#F58518", "address": "#54A24B", "bank": "#B279A2"}


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


@st.cache_data(show_spinner=False)
def _cases(path: str, mtime: float, cases_mtime: float) -> pd.DataFrame:
    base = pd.read_parquet(S.CASES).drop(columns=HARNESS_COLS, errors="ignore")
    return harness.evaluate_all(base, harness.load_policy(path))


def cases() -> pd.DataFrame:
    """Fused cases re-evaluated under the selected policy (cheap; cached per policy file version)."""
    pol = policy()
    return _cases(pol["_path"], _mtime(Path(pol["_path"])), _mtime(S.CASES))


@st.cache_data(show_spinner=False)
def _ranked(path: str, mtime: float, cases_mtime: float, investigators: int, horizon: int) -> pd.DataFrame:
    q = Q.rank(_cases(path, mtime, cases_mtime), harness.load_policy(path), investigators=investigators, horizon=horizon)
    return q


def ranked() -> pd.DataFrame:
    pol = policy()
    inv = int(st.session_state.get("investigators", pol["capacity"]["investigators"]))
    return _ranked(pol["_path"], _mtime(Path(pol["_path"])), _mtime(S.CASES), inv, int(st.session_state.get("horizon") or 90))


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
    net = Network(height="520px", width="100%", cdn_resources="in_line", bgcolor="#ffffff")
    for n, d in sub.nodes(data=True):
        kind = d.get("kind", "?")
        hot = n in highlight
        net.add_node(n, label=n if kind != "member" else "", title=f"{kind} {n} {d.get('type', '')}",
                     color="#E45756" if hot else KIND_COLOR.get(kind, "#999"), size=22 if hot else (8 if kind == "member" else 14))
    for u, v, d in sub.edges(data=True):
        net.add_edge(u, v, title=d.get("rel", ""), color="#E45756" if d.get("rel") == "refers" else "#cccccc",
                     width=2 if d.get("rel") == "refers" else 1)
    net.toggle_physics(True)
    return net.generate_html(), sub.number_of_nodes()


def chips(classes) -> str:
    return " ".join(f":blue-badge[{c}]" for c in classes)
