"""P4 exit check: headless cold/warm page-load timings via AppTest. Run: python -m eval.ui_check"""
import sys
import time

from streamlit.testing.v1 import AppTest

from core import schema as S

APP = str(S.ROOT / "ui" / "app.py")
PAGES = ["views/1_Overview.py", "views/2_Queue.py", "views/3_Case.py", "views/4_Network.py", "views/5_Policy.py",
         "views/6_Ledger.py"]
WARM_MAX_S = 3.0


def load(page: str, network: bool = False) -> tuple[float, bool]:
    at = AppTest.from_file(APP, default_timeout=120)
    t0 = time.time()
    at.run()
    if page != PAGES[0]:
        at.switch_page(page).run()
    if network:
        at.toggle[0].set_value(True).run()
    return time.time() - t0, not at.exception


def main() -> int:
    ok = True
    for page in PAGES + ["views/3_Case.py+network"]:
        p, net = page.split("+")[0], page.endswith("network")
        cold, c_ok = load(p, net)
        warm, w_ok = load(p, net)
        good = c_ok and w_ok and warm < WARM_MAX_S
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {page:28s} cold {cold:5.2f}s  warm {warm:5.2f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
