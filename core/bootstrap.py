"""Cold-start bootstrap for hosted demos (ephemeral disk): if generated data, models or signing keys are missing,
rebuild them once (generator + pipeline with a fresh ledger; the shipped policy is re-signed by siu.lead).
An exclusive file lock makes concurrent first visitors wait for one build instead of running it twice."""
import fcntl
import subprocess
import sys
from pathlib import Path

from core import identity, predict
from core import schema as S
from core.snapshots import HORIZONS

TABLES = ["claims", "members", "providers", "addresses", "referrals", "investigations", "alerts_rules",
          "alerts_anomaly", "alerts_graph", "graph_features", "snapshots", "predictions", "cases"]


def lock_path() -> Path:
    return S.OUT.parent / ".bootstrap.lock"


def missing() -> list[str]:
    """Relative paths (repo root) of required demo artifacts that do not exist."""
    need = [S.OUT / f"{t}.parquet" for t in TABLES] + [S.RUN_META, identity.keys_dir() / "registry.json"]
    need += [predict.MODELS / f"lgbm_h{h}.txt" for h in HORIZONS]
    return [str(p.relative_to(S.ROOT)) if p.is_relative_to(S.ROOT) else str(p) for p in need if not p.exists()]


def needs_bootstrap() -> bool:
    return bool(missing())


def build() -> None:
    """Generator + pipeline in child processes: their memory (pipeline peak ~0.6 GB) is returned to the OS when they
    exit instead of staying in the long-running app server."""
    for args in (["data.gen.synth"], ["core.pipeline", "--reset-ledger"]):
        subprocess.run([sys.executable, "-m", *args], cwd=S.ROOT, check=True, stdout=subprocess.DEVNULL)


def ensure_demo_data(run=build) -> bool:
    """Builds the demo once under an exclusive lock; returns True if this call did the build."""
    lock = lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            if not needs_bootstrap():  # another visitor finished it while we waited
                return False
            run()
            return True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
