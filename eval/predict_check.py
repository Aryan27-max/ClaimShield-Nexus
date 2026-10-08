"""P5 exit check: per-horizon test metrics vs a naive baseline ("strong flag in last 90 d"), new-onset AUC,
timings. Run: python -m eval.predict_check (after python -m core.pipeline)"""
import sys
import time

import pandas as pd

from core import predict as P
from core import schema as S
from core.snapshots import HORIZONS

MIN_AUC = 0.7


def main() -> int:
    snap = pd.read_parquet(S.OUT / "snapshots.parquet")
    rows, ok = [], True
    t0 = time.time()
    for h in HORIZONS:
        model, iso, rep = P.train(snap, h)
        test = P.split(snap, h)["test"]
        test = test.assign(p=iso.predict(model.predict_proba(test[P.FEATURES])[:, 1]),
                           raw=model.predict_proba(test[P.FEATURES])[:, 1], bl=test.bl_strong_90d)
        y = f"label_{h}"
        new = test[test.bl_strong_ever == 0]
        for name, sc, df in [("model", "p", test), ("baseline", "bl", test), ("model new-onset", "raw", new),
                             ("baseline new-onset", "bl", new)]:
            rows.append({"h": h, "scorer": name, **P.metrics(df, sc, y)})
        ok &= (rep["test"]["roc_auc"] or 0) >= MIN_AUC
    train_s = time.time() - t0
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"train+eval 3 horizons {train_s:.1f}s; test ranges {rep['ranges']}")
    ok &= train_s < 20
    print(("PASS" if ok else "FAIL") + f" model ROC-AUC >= {MIN_AUC} on every horizon; training < 20 s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
