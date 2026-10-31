"""Check the hand-written statistics against statsmodels reference implementations."""
import sys
from pathlib import Path

import pytest
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_effectsize, proportions_ztest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from stats_utils import mde_for_n, required_n_per_arm, srm_test, two_proportion_test  # noqa: E402


def test_z_test_matches_statsmodels():
    x_c, n_c, x_t, n_t = 17489, 145274, 17264, 145310
    ours = two_proportion_test(x_c, n_c, x_t, n_t)
    z, p = proportions_ztest([x_t, x_c], [n_t, n_c])
    assert ours.z == pytest.approx(z, rel=1e-9)
    assert ours.p_value == pytest.approx(p, rel=1e-9)


def test_ci_matches_statsmodels_wald():
    x_c, n_c, x_t, n_t = 1200, 10000, 1300, 10000
    ours = two_proportion_test(x_c, n_c, x_t, n_t)
    lo, hi = confint_proportions_2indep(x_t, n_t, x_c, n_c, method="wald", compare="diff")
    assert ours.ci_low == pytest.approx(lo, rel=1e-9)
    assert ours.ci_high == pytest.approx(hi, rel=1e-9)


def test_srm_flags_imbalance_and_passes_balance():
    assert srm_test(50_000, 50_100) > 0.05
    assert srm_test(50_000, 52_000) < 0.001


def test_required_n_close_to_statsmodels():
    p, mde = 0.12, 0.005
    ours = required_n_per_arm(p, mde)
    ref = NormalIndPower().solve_power(proportion_effectsize(p + mde, p), alpha=0.05, power=0.8)
    assert ours == pytest.approx(ref, rel=0.02)


def test_mde_and_required_n_are_consistent():
    n = required_n_per_arm(0.12, 0.005)
    assert mde_for_n(0.12, n) == pytest.approx(0.005, rel=0.02)
