"""History checks: water years, volumes, the San Marcial inflow, storage change and the water balance."""

import pandas as pd
import pytest

from nmreports import history_checks as hc


def days(start, n, cfs):
    return pd.DataFrame({"date": pd.date_range(start, periods=n, freq="D"), "cfs": cfs})


def test_water_year_runs_october_to_september():
    assert list(hc.water_year(["1955-09-30", "1955-10-01", "1956-09-30"])) == [1955, 1956, 1956]


def test_annual_volume_is_cfs_days_in_acre_feet_and_short_years_are_dropped():
    full = days("1955-10-01", 366, 100.0)            # water year 1956 (leap)
    short = days("1956-10-01", 200, 100.0)           # water year 1957, too short
    out = hc.annual_af(pd.concat([full, short]))
    assert list(out["wy"]) == [1956]
    assert out["af"].iloc[0] == pytest.approx(366 * 100 * 1.983471)


def test_san_marcial_inflow_uses_the_whole_river_gauge_while_it_runs_then_floodway_plus_channel():
    main = days("1951-09-28", 6, 500.0)              # the whole-river gauge, ending 1951-10-03
    floodway = days("1951-10-01", 6, 300.0)          # the floodway alone is less than the whole river while both run
    channel = days("1951-10-05", 2, 150.0)
    out = hc.san_marcial_inflow(main, floodway, channel)
    assert list(out["cfs"]) == [500.0] * 6 + [300.0, 450.0, 450.0]
    assert list(out["basis"]).count("whole river") == 6


def test_storage_change_is_end_to_end_and_not_across_a_missing_year():
    stor = pd.DataFrame({"date": pd.to_datetime(["1955-09-30", "1956-09-30", "1958-09-30"]), "af": [100.0, 80.0, 50.0]})
    out = hc.wy_storage(stor).set_index("wy")
    assert out.loc[1956, "change_af"] == -20.0
    assert pd.isna(out.loc[1958, "change_af"])        # 1957 is missing


def test_balance_residual_and_evaporation():
    t = pd.DataFrame({"inflow_af": [1000.0], "release_af": [700.0], "change_af": [100.0], "area_acres": [20000.0]})
    out = hc.balance(t, evap_ft=6.0)
    assert out["residual_af"].iloc[0] == -200.0       # 300 came in net, storage rose only 100
    assert out["evap_af"].iloc[0] == 120000.0
    assert out["unexplained_af"].iloc[0] == 119800.0


def test_climate_needs_twelve_months():
    rows = [{"site_uid": "d", "date": d, "variable": v, "value": 1.0}
            for d in pd.date_range("1955-10-01", periods=12, freq="MS") for v in ("precip", "pdsi")]
    rows.append({"site_uid": "d", "date": pd.Timestamp("1956-10-01"), "variable": "precip", "value": 2.0})
    out = hc.wy_climate(pd.DataFrame(rows))
    assert list(out["wy"]) == [1956] and out["precip_in"].iloc[0] == 12.0 and out["pdsi"].iloc[0] == 1.0


def test_period_summary_counts_years():
    t = pd.DataFrame({"wy": [1950, 1951, 1952, 1990], "x": [1.0, None, 3.0, 9.0]})
    out = hc.period_summary(t, {"early": (1950, 1959), "late": (1990, 1990)}, ["x"]).set_index("period")
    assert out.loc["early", "x"] == 2.0 and out.loc["early", "x_years"] == 2 and out.loc["late", "x"] == 9.0


def test_seasonal_takes_only_the_listed_months_and_needs_all_of_them():
    rows = [{"site_uid": "d", "date": d, "variable": "precip", "value": float(d.month)} for d in pd.date_range("1955-10-01", periods=12, freq="MS")]
    out = hc.seasonal(pd.DataFrame(rows), "precip", [11, 12, 1, 2, 3, 4])
    assert list(out["wy"]) == [1956] and out["value"].iloc[0] == 11 + 12 + 1 + 2 + 3 + 4
    short = pd.DataFrame([r for r in rows if r["date"].month != 2])
    assert hc.seasonal(short, "precip", [11, 12, 1, 2, 3, 4]).empty
