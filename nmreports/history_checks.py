"""Checks behind a feature's history: the per-water-year numbers that test what sources say about a river or reservoir.

Data only (no wording, no drawing). The first user is the Elephant Butte history (history/elephant-butte/report.md, written by
scripts/elephant_butte.py): was the lake low from the 1950s to about 1980 because of drought, because less water reached it, or because more
left it? Every function here is pure; the script does the reading.

Water year: October to September, named for the year it ends in (water year 1956 is 1 Oct 1955 to 30 Sep 1956).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nmwater.derived.reservoirs import CFS_DAY_AF

MIN_DAYS = 330        # days of 365 a water year needs before its volume is counted


def water_year(dates) -> pd.Series:
    """The water year of each date (October to September, named for the September)."""
    d = pd.to_datetime(pd.Series(dates))
    return (d.dt.year + (d.dt.month >= 10)).astype(int)


def annual_af(daily: pd.DataFrame, min_days: int = MIN_DAYS) -> pd.DataFrame:
    """Volume per water year from daily mean cfs. daily has date, cfs. A year with fewer than min_days values is dropped (not scaled up)."""
    if daily.empty:
        return pd.DataFrame(columns=["wy", "af", "days"])
    d = daily.dropna(subset=["cfs"]).assign(wy=lambda x: water_year(x["date"]).values)
    g = d.groupby("wy").agg(af=("cfs", lambda s: float(s.sum() * CFS_DAY_AF)), days=("cfs", "size")).reset_index()
    return g[g["days"] >= min_days].reset_index(drop=True)


def san_marcial_inflow(main: pd.DataFrame, floodway: pd.DataFrame, channel: pd.DataFrame) -> pd.DataFrame:
    """Daily flow of the Rio Grande into Elephant Butte at San Marcial, one series from three gauges.

    "Rio Grande at San Marcial" (USGS 08358500) is the whole river: before the split, and while it was kept (to 1964) as the total of the floodway
    and the Low Flow Conveyance Channel (in 1953-1964 it equals their sum to the acre-foot). It is used on every day it has a value. On other days
    the inflow is the floodway (08358400) plus the channel (08358300), the channel counting as 0 on a day it has no value. In 1951-1952 the floodway
    alone is far below the whole river (1952: 685,000 against 967,000 acre-feet), so the floodway is never used where the total exists.
    Each frame has date, cfs. Returns date, cfs, basis ('whole river' or 'floodway + channel')."""
    m = main.set_index(pd.to_datetime(main["date"]))["cfs"].dropna() if len(main) else pd.Series(dtype=float)
    f = floodway.set_index(pd.to_datetime(floodway["date"]))["cfs"] if len(floodway) else pd.Series(dtype=float)
    c = channel.set_index(pd.to_datetime(channel["date"]))["cfs"] if len(channel) else pd.Series(dtype=float)
    parts = f.add(c.reindex(f.index).fillna(0.0), fill_value=0.0) if len(f) else pd.Series(dtype=float)
    parts = parts[~parts.index.isin(m.index)]
    out = pd.concat([pd.DataFrame({"date": m.index, "cfs": m.values, "basis": "whole river"}),
                     pd.DataFrame({"date": parts.index, "cfs": parts.values, "basis": "floodway + channel"})], ignore_index=True)
    return out.sort_values("date").reset_index(drop=True)


def wy_storage(stor: pd.DataFrame) -> pd.DataFrame:
    """Storage per water year from daily storage (date, af): mean, the last value of the year, and the change from the previous year's last value."""
    if stor.empty:
        return pd.DataFrame(columns=["wy", "mean_af", "end_af", "change_af", "days"])
    d = stor.dropna(subset=["af"]).sort_values("date").assign(wy=lambda x: water_year(x["date"]).values)
    g = d.groupby("wy").agg(mean_af=("af", "mean"), end_af=("af", "last"), days=("af", "size")).reset_index()
    g["change_af"] = g["end_af"].diff()
    g.loc[g["wy"].diff() != 1, "change_af"] = np.nan          # no change across a missing year
    return g


def balance(t: pd.DataFrame, evap_ft: float | None = None) -> pd.DataFrame:
    """The reservoir's water balance per year. t has inflow_af, release_af, change_af and optionally area_acres (mean surface area).

    residual_af = change in storage - (inflow - release): what the gauges do not account for (evaporation, seepage, local inflow, gauge error).
    With an evaporation depth in feet per year, evap_af = area x depth and unexplained_af = residual + evaporation."""
    out = t.copy()
    out["residual_af"] = out["change_af"] - (out["inflow_af"] - out["release_af"])
    if evap_ft is not None and "area_acres" in out:
        out["evap_af"] = out["area_acres"] * evap_ft
        out["unexplained_af"] = out["residual_af"] + out["evap_af"]
    return out


def wy_climate(monthly: pd.DataFrame) -> pd.DataFrame:
    """Water-year precipitation total and mean PDSI per climate division. monthly has site_uid, date, variable ('precip' in inches, 'pdsi'), value.
    A year counts only with all 12 months."""
    if monthly.empty:
        return pd.DataFrame(columns=["wy", "site_uid", "precip_in", "pdsi"])
    d = monthly.assign(wy=water_year(monthly["date"]).values)
    p = d[d.variable == "precip"].groupby(["wy", "site_uid"])["value"].agg(["sum", "size"]).reset_index()
    p = p[p["size"] == 12].rename(columns={"sum": "precip_in"}).drop(columns="size")
    q = d[d.variable == "pdsi"].groupby(["wy", "site_uid"])["value"].agg(["mean", "size"]).reset_index()
    q = q[q["size"] == 12].rename(columns={"mean": "pdsi"}).drop(columns="size")
    return p.merge(q, on=["wy", "site_uid"], how="outer").sort_values(["site_uid", "wy"]).reset_index(drop=True)


def seasonal(monthly: pd.DataFrame, variable: str, months: list[int], how: str = "sum") -> pd.DataFrame:
    """One value per water year and site from the given months only (e.g. November-April precipitation, the snow season; March-June
    temperature, the melt season). A year counts only when every listed month is present. Returns wy, site_uid, value."""
    d = monthly[(monthly.variable == variable)].copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"].dt.month.isin(months)].assign(wy=lambda x: water_year(x["date"]).values)
    g = d.groupby(["wy", "site_uid"])["value"].agg([how, "size"]).reset_index()
    return g[g["size"] == len(months)].rename(columns={how: "value"}).drop(columns="size").reset_index(drop=True)


def period_summary(t: pd.DataFrame, periods: dict[str, tuple[int, int]], cols: list[str]) -> pd.DataFrame:
    """Mean of each column over named water-year periods (inclusive), with how many years had a value."""
    rows = []
    for name, (a, b) in periods.items():
        sub = t[(t["wy"] >= a) & (t["wy"] <= b)]
        row = {"period": name, "from": a, "to": b}
        for c in cols:
            v = sub[c].dropna() if c in sub else pd.Series(dtype=float)
            row[c] = float(v.mean()) if len(v) else None
            row[f"{c}_years"] = int(len(v))
        rows.append(row)
    return pd.DataFrame(rows)
