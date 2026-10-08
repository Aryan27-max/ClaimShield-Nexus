import threading
import time

from core import bootstrap as B
from core import identity, predict
from core import schema as S


def test_complete_demo_needs_no_bootstrap():
    assert B.missing() == []


def test_missing_artifacts_are_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OUT", tmp_path / "out")
    monkeypatch.setattr(S, "RUN_META", tmp_path / "out" / "run_meta.json")
    monkeypatch.setattr(predict, "MODELS", tmp_path / "models")
    monkeypatch.setattr(identity, "KEYS_DIR", tmp_path / "keys")
    miss = B.missing()
    assert B.needs_bootstrap() and len(miss) == len(B.TABLES) + 2 + 3
    assert any(m.endswith("registry.json") for m in miss) and any("lgbm_h90" in m for m in miss)


def test_concurrent_first_visitors_build_once(tmp_path, monkeypatch):
    state = {"done": False, "runs": 0}
    monkeypatch.setattr(B, "lock_path", lambda: tmp_path / ".bootstrap.lock")
    monkeypatch.setattr(B, "needs_bootstrap", lambda: not state["done"])

    def slow_build():
        state["runs"] += 1
        time.sleep(0.3)
        state["done"] = True
    results = []
    threads = [threading.Thread(target=lambda: results.append(B.ensure_demo_data(slow_build))) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["runs"] == 1 and sorted(results) == [False, False, True]
