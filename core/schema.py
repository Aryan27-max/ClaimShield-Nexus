"""Shared constants: paths, seed, enums and code tables."""
from pathlib import Path

import pandas as pd

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "out"
LEDGER_DB = OUT / "ledger.db"

START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2025-06-30")

N_MEMBERS = 15_000
N_PROVIDERS = 1_200
MAX_CLAIMS = 150_000

PROVIDER_TYPES = ["prof", "facility", "pharmacy", "lab", "ambulance", "bh", "home_health", "dme"]
SCHEMES = [
    "duplicate_billing", "upcoding", "unbundling", "phantom_services",
    "excessive_units", "impossible_timing", "dme_ring", "kickback_referral",
]
OUTCOMES = ["confirmed", "unfounded", "education"]
LENSES = ["rules", "anomaly", "graph", "predict"]
ALERT_COLUMNS = [
    "alert_id", "lens", "entity_type", "entity_id", "claim_ids", "code",
    "severity", "score", "dollars_at_risk", "evidence",
]

# Synthetic regions (name, lat, lon, member share)
CLUSTERS = [
    ("houston", 29.76, -95.37, 0.28), ("dallas", 32.78, -96.80, 0.26),
    ("san_antonio", 29.42, -98.49, 0.16), ("austin", 30.27, -97.74, 0.14),
    ("el_paso", 31.76, -106.49, 0.08), ("amarillo", 35.22, -101.83, 0.08),
]

# cpt: (description, category, fee, mue, minutes_per_unit, units_lo, units_hi)
CPT = {
    "99211": ("E/M est L1", "em", 25, 1, 5, 1, 1),
    "99212": ("E/M est L2", "em", 50, 1, 10, 1, 1),
    "99213": ("E/M est L3", "em", 90, 1, 15, 1, 1),
    "99214": ("E/M est L4", "em", 130, 1, 25, 1, 1),
    "99215": ("E/M est L5", "em", 180, 1, 40, 1, 1),
    "99283": ("ER visit L3", "er", 120, 1, 20, 1, 1),
    "99284": ("ER visit L4", "er", 210, 1, 30, 1, 1),
    "99285": ("ER visit L5", "er", 310, 1, 45, 1, 1),
    "90791": ("Psych diagnostic eval", "bh", 160, 1, 60, 1, 1),
    "90834": ("Psychotherapy 45 min", "bh", 110, 1, 45, 1, 1),
    "90837": ("Psychotherapy 60 min", "bh", 150, 1, 60, 1, 1),
    "97110": ("Therapeutic exercise 15 min", "pt", 32, 4, 15, 1, 4),
    "97140": ("Manual therapy 15 min", "pt", 30, 4, 15, 1, 4),
    "97530": ("Therapeutic activities 15 min", "pt", 35, 4, 15, 1, 4),
    "80053": ("Comprehensive metabolic panel", "lab", 15, 1, 0, 1, 1),
    "80048": ("Basic metabolic panel", "lab", 11, 1, 0, 1, 1),
    "85025": ("CBC with diff", "lab", 10, 1, 0, 1, 1),
    "85027": ("CBC automated", "lab", 8, 1, 0, 1, 1),
    "36415": ("Venipuncture", "lab", 3, 1, 0, 1, 1),
    "81001": ("Urinalysis", "lab", 4, 1, 0, 1, 1),
    "71046": ("Chest x-ray 2 views", "rad", 35, 1, 10, 1, 1),
    "70450": ("CT head w/o contrast", "rad", 120, 1, 15, 1, 1),
    "70470": ("CT head w/o & with contrast", "rad", 200, 1, 20, 1, 1),
    "93000": ("ECG with interpretation", "card", 18, 1, 10, 1, 1),
    "93010": ("ECG interpretation only", "card", 8, 1, 5, 1, 1),
    "20610": ("Arthrocentesis major joint", "proc", 65, 2, 15, 1, 1),
    "96413": ("Chemo infusion first hour", "onc", 150, 1, 60, 1, 1),
    "96360": ("Hydration infusion first hour", "onc", 55, 1, 60, 1, 1),
    "J9271": ("Pembrolizumab 1 mg", "onc", 55, 400, 0, 100, 220),
    "E0601": ("CPAP device", "dme", 900, 1, 0, 1, 1),
    "K0001": ("Standard wheelchair", "dme", 600, 1, 0, 1, 1),
    "E0260": ("Semi-electric hospital bed", "dme", 1500, 1, 0, 1, 1),
    "L1832": ("Knee orthosis", "dme", 700, 2, 0, 1, 2),
    "A4253": ("Glucose test strips (50)", "dme", 35, 3, 0, 1, 3),
    "G0299": ("Home health RN 15 min", "hh", 45, 8, 15, 2, 8),
    "G0156": ("Home health aide 15 min", "hh", 25, 8, 15, 2, 8),
    "A0427": ("ALS emergency transport", "amb", 500, 1, 0, 1, 1),
    "A0425": ("Ground mileage per mile", "amb", 8, 250, 0, 5, 60),
    "RX100": ("Generic drug fill", "rx", 40, 3, 0, 1, 3),
    "RX200": ("Brand drug fill", "rx", 350, 2, 0, 1, 2),
}
EM_LEVELS = ["99211", "99212", "99213", "99214", "99215"]
EM_BASE_MIX = [0.05, 0.15, 0.45, 0.28, 0.07]

# NCCI procedure-to-procedure pairs: (column1, column2); column2 is bundled into column1
NCCI_PAIRS = [
    ("80053", "80048"), ("85025", "85027"), ("93000", "93010"), ("70470", "70450"),
    ("96413", "96360"), ("97140", "97530"), ("99214", "99213"),
]

GEO_IMPOSSIBLE_KM = 300
MAX_MINUTES_PER_DAY = 1440
TIMED_PROVIDER_TYPES = ["prof", "bh", "home_health"]


def cpt_table() -> pd.DataFrame:
    """CPT code table as a DataFrame indexed by cpt."""
    cols = ["desc", "category", "fee", "mue", "minutes_per_unit", "units_lo", "units_hi"]
    return pd.DataFrame.from_dict(CPT, orient="index", columns=cols).rename_axis("cpt")
