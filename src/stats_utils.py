"""Small, testable statistics helpers for analysing a two-arm conversion A/B test."""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from scipy import stats


@dataclass
class TwoPropResult:
    p_control: float
    p_treatment: float
    abs_diff: float          # treatment - control, in proportion units
    rel_lift: float          # abs_diff / p_control
    z: float
    p_value: float           # two-sided
    ci_low: float            # CI for abs_diff (unpooled SE)
    ci_high: float


def two_proportion_test(x_c: int, n_c: int, x_t: int, n_t: int, alpha: float = 0.05) -> TwoPropResult:
    """Two-sided pooled z-test for H0: p_t == p_c, plus a Wald CI for the difference."""
    p_c, p_t = x_c / n_c, x_t / n_t
    diff = p_t - p_c
    p_pool = (x_c + x_t) / (n_c + n_t)
    se_pool = sqrt(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t))
    z = diff / se_pool
    p_value = 2 * stats.norm.sf(abs(z))
    se_unpooled = sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    z_crit = stats.norm.ppf(1 - alpha / 2)
    return TwoPropResult(p_c, p_t, diff, diff / p_c, z, p_value,
                         diff - z_crit * se_unpooled, diff + z_crit * se_unpooled)


def srm_test(n_c: int, n_t: int, expected_share_c: float = 0.5) -> float:
    """Sample-ratio-mismatch chi-square test. Returns the p-value."""
    total = n_c + n_t
    expected = [total * expected_share_c, total * (1 - expected_share_c)]
    return float(stats.chisquare([n_c, n_t], f_exp=expected).pvalue)


def required_n_per_arm(p_base: float, mde_abs: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Users needed per arm to detect an absolute lift `mde_abs` with a two-sided test."""
    p_alt = p_base + mde_abs
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    p_bar = (p_base + p_alt) / 2
    num = (z_a * sqrt(2 * p_bar * (1 - p_bar)) + z_b * sqrt(p_base * (1 - p_base) + p_alt * (1 - p_alt))) ** 2
    return int(-(-num // (mde_abs ** 2)))  # ceil


def mde_for_n(p_base: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Approximate minimum detectable absolute effect for a given per-arm sample size."""
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    return (z_a + z_b) * sqrt(2 * p_base * (1 - p_base) / n_per_arm)
