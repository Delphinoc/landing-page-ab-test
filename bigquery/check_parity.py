"""Check that the BigQuery port reproduces the DuckDB results.

1. Export the BigQuery result:
   bq query --nouse_legacy_sql --format=json \
     'SELECT * FROM ab_test.primary_result' > bigquery/bq_primary_result.json
   (or in the console: run the SELECT, then Save results -> JSON)
2. python bigquery/check_parity.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BQ = ROOT / "bigquery" / "bq_primary_result.json"
REF = ROOT / "reports" / "results.json"


def two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def main() -> int:
    text = BQ.read_text().strip()
    try:
        bq = json.loads(text)
    except json.JSONDecodeError:  # newline-delimited JSON export
        bq = json.loads(text.splitlines()[0])
    bq = bq[0] if isinstance(bq, list) else bq
    ref = json.loads(REF.read_text())["primary"]
    z = float(bq["z"])
    checks = {
        "control_cr_pct": (float(bq["control_cr_pct"]), ref["control_cr_pct"]),
        "treatment_cr_pct": (float(bq["treatment_cr_pct"]), ref["treatment_cr_pct"]),
        "diff_pp": (float(bq["diff_pp"]), ref["diff_pp"]),
        "ci_low_pp": (float(bq["ci_low_pp"]), ref["ci95_pp"][0]),
        "ci_high_pp": (float(bq["ci_high_pp"]), ref["ci95_pp"][1]),
        "z": (z, ref["z"]),
        "p_value": (round(two_sided_p(z), 4), ref["p_value"]),
    }
    ok = True
    for name, (got, want) in checks.items():
        match = abs(got - want) <= 0.002
        ok &= match
        print(f"{'OK ' if match else 'DIFF'}  {name:18s} BigQuery={got:<10} DuckDB={want}")
    print("\nParity confirmed." if ok else "\nMismatch - investigate before claiming parity.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
