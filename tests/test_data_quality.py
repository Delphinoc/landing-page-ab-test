"""Data-quality checks on the cleaned experiment table built by the SQL pipeline."""
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from run_analysis import build_tables  # noqa: E402


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    build_tables(c)
    return c


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def test_one_row_per_user(con):
    assert scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT user_id) FROM ab_clean") == 0


def test_no_group_page_mismatch(con):
    assert scalar(con, """
        SELECT COUNT(*) FROM ab_clean
        WHERE NOT ((assigned_group = 'control' AND landing_page = 'old_page')
                OR (assigned_group = 'treatment' AND landing_page = 'new_page'))""") == 0


def test_only_two_arms(con):
    arms = {r[0] for r in con.execute("SELECT DISTINCT assigned_group FROM ab_clean").fetchall()}
    assert arms == {"control", "treatment"}


def test_converted_is_binary_and_not_null(con):
    assert scalar(con, "SELECT COUNT(*) FROM ab_clean WHERE converted IS NULL OR converted NOT IN (0, 1)") == 0


def test_every_user_has_a_country(con):
    assert scalar(con, "SELECT COUNT(*) FROM ab_clean WHERE country IS NULL") == 0


def test_no_null_timestamps(con):
    assert scalar(con, "SELECT COUNT(*) FROM ab_clean WHERE event_ts IS NULL") == 0


def test_cleaning_drops_only_mismatches_and_duplicates(con):
    raw = scalar(con, "SELECT COUNT(*) FROM raw_events")
    mismatched = scalar(con, "SELECT SUM(n_rows) FROM assignment_issues")
    valid_rows = raw - mismatched
    valid_users = scalar(con, """
        SELECT COUNT(DISTINCT user_id) FROM raw_events
        WHERE (assigned_group = 'control' AND landing_page = 'old_page')
           OR (assigned_group = 'treatment' AND landing_page = 'new_page')""")
    clean = scalar(con, "SELECT COUNT(*) FROM ab_clean")
    assert clean == valid_users
    assert valid_rows - clean >= 0


def test_metric_tables_reconcile(con):
    assert scalar(con, "SELECT SUM(users) FROM arm_metrics") == scalar(con, "SELECT COUNT(*) FROM ab_clean")
    assert scalar(con, "SELECT SUM(users) FROM daily_metrics") == scalar(con, "SELECT COUNT(*) FROM ab_clean")
    assert scalar(con, "SELECT SUM(conversions) FROM country_metrics") == scalar(con, "SELECT SUM(converted) FROM ab_clean")
