"""End-to-end analysis of the landing-page A/B test.

Run from the project root:
    python src/run_analysis.py

Steps
1. DuckDB SQL: clean the raw log and build metric tables (sql/01_clean.sql, sql/02_metrics.sql)
2. Experiment health: assignment/logging issues and sample-ratio-mismatch (SRM) check
3. Primary result: two-proportion z-test + 95% CI on the conversion-rate difference
4. Power: was the test big enough? (MDE achieved vs the pre-set business threshold)
5. Robustness: novelty check over time, "peeking" check on cumulative results,
   country segments (exploratory, Holm-corrected) and logistic regression
6. Decision against the pre-specified rule; results written to reports/
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from stats_utils import mde_for_n, required_n_per_arm, srm_test, two_proportion_test  # noqa: E402

DATA_DIR = ROOT / "data" / "raw"
REPORTS = ROOT / "reports"
FIGS = REPORTS / "figures"

# ---- Pre-specified decision rule (set before looking at results) -------------
ALPHA = 0.05
POWER = 0.80
# Assumption for this case study: the new page must lift conversion by at least
# 0.5 percentage points to be worth the build and maintenance cost.
PRACTICAL_MDE_ABS = 0.005


def build_tables(con: duckdb.DuckDBPyConnection) -> None:
    for name in ("01_clean.sql", "02_metrics.sql"):
        sql = (ROOT / "sql" / name).read_text().replace("{data_dir}", DATA_DIR.as_posix())
        con.execute(sql)


def arm_counts(df: pd.DataFrame) -> tuple[int, int, int, int]:
    c = df.set_index("assigned_group")
    return (int(c.loc["control", "conversions"]), int(c.loc["control", "users"]),
            int(c.loc["treatment", "conversions"]), int(c.loc["treatment", "users"]))


def pp(x: float) -> float:
    """Proportion -> percentage points, rounded for reporting."""
    return round(100 * x, 3)


def main() -> dict:
    FIGS.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    build_tables(con)

    funnel = con.execute("SELECT * FROM cleaning_funnel").df()
    issues = con.execute("SELECT * FROM assignment_issues ORDER BY ALL").df()
    arms = con.execute("SELECT * FROM arm_metrics").df()
    daily = con.execute("SELECT * FROM daily_metrics").df()
    cum = con.execute("SELECT * FROM cumulative_metrics").df()
    country = con.execute("SELECT * FROM country_metrics").df()
    users = con.execute("SELECT assigned_group, converted, country, event_date FROM ab_clean").df()

    # ---- 2. Experiment health ------------------------------------------------
    x_c, n_c, x_t, n_t = arm_counts(arms)
    srm_p = srm_test(n_c, n_t)
    raw_rows = int(funnel.loc[funnel.step == "raw rows", "n"].iloc[0])
    mismatch_rows = int(issues.n_rows.sum())

    # ---- 3. Primary result ---------------------------------------------------
    res = two_proportion_test(x_c, n_c, x_t, n_t, alpha=ALPHA)

    # ---- 4. Power ------------------------------------------------------------
    n_needed = required_n_per_arm(res.p_control, PRACTICAL_MDE_ABS, ALPHA, POWER)
    mde_achieved = mde_for_n(res.p_control, min(n_c, n_t), ALPHA, POWER)

    # ---- 5a. Novelty: first vs second half of the test ------------------------
    dates = sorted(users.event_date.unique())
    split = dates[len(dates) // 2]
    users["period"] = (users.event_date >= split).map({False: "first_half", True: "second_half"})
    users["treatment"] = (users.assigned_group == "treatment").astype(int)
    period_rows = []
    for period, g in users.groupby("period"):
        gc = g[g.treatment == 0]
        gt = g[g.treatment == 1]
        r = two_proportion_test(int(gc.converted.sum()), len(gc), int(gt.converted.sum()), len(gt))
        period_rows.append({"period": period, "diff_pp": pp(r.abs_diff), "p_value": round(r.p_value, 4)})
    novelty_model = smf.logit("converted ~ treatment * C(period)", data=users).fit(disp=False)
    novelty_interaction_p = float(novelty_model.pvalues["treatment:C(period)[T.second_half]"])

    # ---- 5b. Peeking: cumulative p-value by day -------------------------------
    peek_rows = []
    for d, g in cum.groupby("event_date"):
        g = g.set_index("assigned_group")
        r = two_proportion_test(int(g.loc["control", "cum_conversions"]), int(g.loc["control", "cum_users"]),
                                int(g.loc["treatment", "cum_conversions"]), int(g.loc["treatment", "cum_users"]))
        peek_rows.append({"event_date": pd.Timestamp(d), "diff_pp": 100 * r.abs_diff,
                          "ci_low_pp": 100 * r.ci_low, "ci_high_pp": 100 * r.ci_high, "p_value": r.p_value})
    peek = pd.DataFrame(peek_rows)
    days_significant = int((peek.p_value < ALPHA).sum())
    min_peek_p = float(peek.p_value.min())

    # ---- 5c. Country segments (exploratory) ----------------------------------
    seg_rows = []
    for ctry, g in country.groupby("country"):
        cx_c, cn_c, cx_t, cn_t = arm_counts(g)
        r = two_proportion_test(cx_c, cn_c, cx_t, cn_t)
        seg_rows.append({"country": ctry, "users": cn_c + cn_t, "control_cr_pct": pp(r.p_control),
                         "treatment_cr_pct": pp(r.p_treatment), "diff_pp": pp(r.abs_diff),
                         "ci_low_pp": pp(r.ci_low), "ci_high_pp": pp(r.ci_high), "p_value": r.p_value})
    seg = pd.DataFrame(seg_rows)
    seg["p_holm"] = multipletests(seg.p_value, method="holm")[1]
    seg_model = smf.logit("converted ~ treatment * C(country, Treatment('US'))", data=users).fit(disp=False)
    interaction_terms = [k for k in seg_model.pvalues.index if k.startswith("treatment:")]
    country_interaction_p = {k: float(seg_model.pvalues[k]) for k in interaction_terms}

    # ---- 6. Decision -----------------------------------------------------------
    significant_positive = res.p_value < ALPHA and res.abs_diff > 0
    ci_excludes_target = res.ci_high < PRACTICAL_MDE_ABS
    if significant_positive and res.ci_low > 0:
        decision = "LAUNCH new page"
    elif ci_excludes_target and mde_achieved <= PRACTICAL_MDE_ABS:
        decision = "DO NOT LAUNCH: keep old page (test was adequately powered; the target lift is ruled out)"
    else:
        decision = "INCONCLUSIVE: extend the test"

    results = {
        "data": {
            "raw_rows": raw_rows,
            "raw_distinct_users": int(funnel.loc[funnel.step == "raw distinct users", "n"].iloc[0]),
            "mismatch_rows": mismatch_rows,
            "mismatch_share_pct": round(100 * mismatch_rows / raw_rows, 2),
            "mismatch_by_cell": issues.to_dict(orient="records"),
            "clean_users": n_c + n_t,
            "test_window": [str(min(dates)), str(max(dates))],
            "test_days_calendar": len(dates),
        },
        "health": {"users_control": n_c, "users_treatment": n_t,
                   "control_share_pct": round(100 * n_c / (n_c + n_t), 3), "srm_p_value": round(srm_p, 4)},
        "primary": {
            "control_cr_pct": pp(res.p_control), "treatment_cr_pct": pp(res.p_treatment),
            "diff_pp": pp(res.abs_diff), "relative_lift_pct": round(100 * res.rel_lift, 2),
            "ci95_pp": [pp(res.ci_low), pp(res.ci_high)], "z": round(res.z, 3), "p_value": round(res.p_value, 4),
        },
        "power": {"practical_mde_pp": pp(PRACTICAL_MDE_ABS), "n_needed_per_arm": n_needed,
                  "n_actual_per_arm_min": min(n_c, n_t), "mde_achieved_pp": pp(mde_achieved)},
        "novelty": {"by_period": period_rows, "split_date": str(split),
                    "interaction_p_value": round(novelty_interaction_p, 4)},
        "peeking": {"days_checked": len(peek), "days_with_p_below_alpha": days_significant,
                    "min_daily_p_value": round(min_peek_p, 4)},
        "segments": {"by_country": seg.round(4).to_dict(orient="records"),
                     "interaction_p_values": {k: round(v, 4) for k, v in country_interaction_p.items()}},
        "decision": decision,
    }
    (REPORTS / "results.json").write_text(json.dumps(results, indent=2, default=str))

    make_figures(res, daily, peek, seg)
    return results


def make_figures(res, daily: pd.DataFrame, peek: pd.DataFrame, seg: pd.DataFrame) -> None:
    c_ctrl, c_trt = "#4C72B0", "#DD8452"
    plt.rcParams.update({"figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False})

    # 1. Primary result: difference with 95% CI vs the practical threshold
    fig, ax = plt.subplots(figsize=(7, 2.6))
    ax.errorbar(100 * res.abs_diff, 0, xerr=[[100 * (res.abs_diff - res.ci_low)], [100 * (res.ci_high - res.abs_diff)]],
                fmt="o", color="#333", capsize=6)
    ax.axvline(0, color="grey", lw=1)
    ax.axvline(100 * PRACTICAL_MDE_ABS, color="#55A868", ls="--", lw=1.5)
    ax.text(100 * PRACTICAL_MDE_ABS, 0.35, " launch target +0.5 pp", color="#55A868", va="center")
    ax.set_yticks([])
    ax.set_ylim(-0.6, 0.6)
    ax.set_xlabel("New page minus old page, conversion rate (percentage points)")
    ax.set_title("Primary result: 95% CI rules out the +0.5 pp launch target")
    fig.tight_layout()
    fig.savefig(FIGS / "01_primary_result.png")
    plt.close(fig)

    # 2. Daily conversion by arm
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for grp, col in (("control", c_ctrl), ("treatment", c_trt)):
        d = daily[daily.assigned_group == grp]
        ax.plot(pd.to_datetime(d.event_date), 100 * d.conversion_rate, marker="o", ms=3, color=col,
                label="Old page (control)" if grp == "control" else "New page (treatment)")
    ax.set_ylabel("Conversion rate (%)")
    ax.set_title("Daily conversion: no sustained gap and no novelty spike")
    ax.legend(frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIGS / "02_daily_conversion.png")
    plt.close(fig)

    # 3. Cumulative difference and p-value (peeking check)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5.2), sharex=True)
    a1.fill_between(peek.event_date, peek.ci_low_pp, peek.ci_high_pp, color="#999", alpha=0.3, label="95% CI")
    a1.plot(peek.event_date, peek.diff_pp, color="#333", label="Cumulative difference")
    a1.axhline(0, color="grey", lw=1)
    a1.set_ylabel("Diff (pp)")
    a1.legend(frameon=False, loc="lower right")
    a1.set_title("Cumulative result by day: the estimate settles near zero as data accrues")
    a2.plot(peek.event_date, peek.p_value, color="#C44E52", marker="o", ms=3)
    a2.axhline(ALPHA, color="grey", ls="--", lw=1)
    a2.set_ylabel("p-value")
    a2.set_ylim(0, 1)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIGS / "03_cumulative_peeking.png")
    plt.close(fig)

    # 4. Country segments
    s = seg.sort_values("diff_pp")
    fig, ax = plt.subplots(figsize=(7, 2.8))
    ax.errorbar(s.diff_pp, range(len(s)), xerr=[s.diff_pp - s.ci_low_pp, s.ci_high_pp - s.diff_pp],
                fmt="o", color="#333", capsize=5)
    ax.set_yticks(range(len(s)), [f"{c} (n={n:,})" for c, n in zip(s.country, s.users)])
    ax.axvline(0, color="grey", lw=1)
    ax.set_xlabel("New minus old conversion (pp), 95% CI")
    ax.set_title("By country: no market where the new page clearly wins")
    fig.tight_layout()
    fig.savefig(FIGS / "04_country_segments.png")
    plt.close(fig)


if __name__ == "__main__":
    out = main()
    print(json.dumps(out, indent=2, default=str))
