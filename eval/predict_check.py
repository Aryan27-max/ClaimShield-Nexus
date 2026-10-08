"""P5 exit check: per-horizon test metrics vs a naive baseline ("strong flag in last 90 d"), new-onset AUC,
timings. Run: python -m eval.predict_check (after python -m core.pipeline)"""
import sys
import time

from core import predict as P
from eval.metrics import model_vs_baseline

MIN_AUC = 0.7


def main() -> int:
    t0 = time.time()
    res = model_vs_baseline()
    train_s = time.time() - t0
    print(res.to_string(index=False))
    model = res[res.scorer == "model"]
    ok = bool((model.roc_auc >= MIN_AUC).all()) and train_s < 20
    print(f"train+eval 3 horizons {train_s:.1f}s (embargoed split, test T >= {P.TEST_START.date()})")
    print(("PASS" if ok else "FAIL") + f" model ROC-AUC >= {MIN_AUC} on every horizon; training < 20 s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
