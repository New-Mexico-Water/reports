"""Per-water-year table behind the Elephant Butte history (history/elephant-butte/report.md).

    uv run python scripts/elephant_butte.py            # writes history/elephant-butte/elephant-butte.csv and elephant-butte-periods.csv

Reads the nmwater DuckDB catalog. Other people's documents and data are never copied into this repository: the Compact Commission's
year-end balances (our transcription of the scanned reports, each linked in history/elephant-butte/references.md) and the USGS allotments
data release are kept in a local folder outside it (SOURCES below; the USGS file is downloaded there on first run). With them, the script
also writes elephant-butte-with-sources.csv to that folder (columns compact_debit_co_af, compact_debit_nm_af, project_storage_dec31_af,
allotment_ft_per_acre, allocation_total_af); the tables committed here hold only numbers computed from the archive.

Run it as a capped unit on this machine (it scans large tables):
    systemd-run --user --wait --pipe --collect -p MemoryMax=8G uv run python scripts/elephant_butte.py

Columns (water years, October to September, acre-feet unless stated):
  otowi_af             Rio Grande at Otowi Bridge (USGS 08313000; Reclamation and Colorado DWR copies fill gaps)
  san_marcial_af       inflow to the lake: Rio Grande at San Marcial (USGS 08358500, the whole river, kept to 1964 as the total of the floodway
                       and the conveyance channel), then the floodway (USGS 08358400) plus the Low Flow Conveyance Channel (USGS 08358300)
  valley_loss_af       otowi_af - san_marcial_af: water that left the river between Otowi and the lake (plus tributary inflow, which offsets it)
  release_af           Rio Grande below Elephant Butte Dam (USGS 08361000)
  caballo_release_af   Rio Grande below Caballo Dam (USGS 08362500, Reclamation copy after 2013): what the Project sent downstream
  eb_mean_af, eb_end_af, eb_change_af   Elephant Butte storage (Reclamation HydroData 1119): year mean, last value, change on the year before
  caballo_mean_af      Caballo storage (Reclamation 1094); project_mean_af = Elephant Butte + Caballo
  eb_area_acres        mean lake surface area (Reclamation 1119)
  residual_af          eb_change_af - (san_marcial_af - release_af): what the gauges do not account for (mostly evaporation)
  del_norte_af, conejos_af, lobatos_af, embudo_af, chamita_af   the gauges above Otowi (USGS 08220000, 08246500, 08251500, 08279500, 08290000)
  co_index_af = del_norte + conejos; co_use_af = co_index - lobatos; nm_north_gain_af = embudo - lobatos; espanola_gain_af = otowi - embudo - chamita
  snow_season_*_in    November-April precipitation; monsoon_*_in July-September; melt_season_*_c March-June mean temperature (co_rg, nm_mtn)
  precip_*_in, pdsi_*  NOAA nClimDiv water-year precipitation and mean Palmer Drought Severity Index: nm = mean of New Mexico's 8 divisions
                       (unweighted), nm_mtn = 2902 Northern Mountains, nm_valley = 2905 Central Valley, co_rg = Colorado 0505
"""

from __future__ import annotations

import os
import urllib.request
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from nmwater.core.config import PROJECT_ROOT as NMWATER_ROOT
from nmreports import history_checks as hc
from nmwater.derived.reservoirs import daily as res_daily, splice
from nmwater.derived.river_flow import pick_copy, read_daily

OUT = Path(__file__).resolve().parents[1] / "history" / "elephant-butte"
SOURCES = Path(os.environ.get("NMREPORTS_SOURCES", Path.home() / ".cache" / "nmreports")) / "elephant-butte"
ALLOTMENTS_URL = ("https://www.sciencebase.gov/catalog/file/get/5ba03abbe4b08583a5c279fe"
                  "?f=__disk__c7%2F38%2F5e%2Fc7385e1833383a14f7cb28a073b80f0f51fc4e3e")   # USGS data release 10.5066/P9J9NYND, Allotments_and_Allocations.csv
THIRD_PARTY = ["compact_debit_co_af", "compact_debit_nm_af", "project_storage_dec31_af", "allotment_ft_per_acre", "allocation_total_af"]
DB = NMWATER_ROOT / "data" / "duckdb" / "nmwater.duckdb"      # the nmwater archive (the nmwater checkout this project depends on)
START, END = date(1895, 1, 1), date(2025, 9, 30)

GAUGES = {   # one series per name; the copies of a gauge in priority order (river_flow.PRIORITY picks per day)
    "otowi": ["usgs:08313000", "usbr_hydrodata:1095", "codwr:RIOOTANM"],
    "sm_main": ["usgs:08358500"],
    "floodway": ["usgs:08358400", "usbr_hydrodata:1542", "codwr:SMFRIONM"],
    "channel": ["usgs:08358300", "usbr_hydrodata:1541", "codwr:SMCRIONM"],
    "release": ["usgs:08361000", "codwr:RIOELENM"],
    "caballo_release": ["usgs:08362500", "usbr_hydrodata:1113"],
    # above Otowi: Colorado's headwaters (Rio Grande near Del Norte, Conejos near Mogote: the Compact's index gauges, little affected upstream),
    # the state line (Lobatos), the Rio Grande above the Chama (Embudo) and the Rio Chama at its mouth (Chamita)
    "del_norte": ["usgs:08220000", "codwr:RIODELCO", "usbr_hydrodata:2722"],
    "conejos": ["usgs:08246500", "codwr:CONMOGCO", "usbr_hydrodata:2741"],
    "lobatos": ["usgs:08251500", "codwr:RIOLOBCO", "usbr_hydrodata:2723"],
    "embudo": ["usgs:08279500", "usbr_hydrodata:1513", "codwr:RIOEMBNM"],
    "chamita": ["usgs:08290000", "usbr_hydrodata:1519", "codwr:RCHCHANM"],
}
DIVISIONS = {"nm_mtn": "nclimdiv:div:2902", "nm_valley": "nclimdiv:div:2905", "co_rg": "nclimdiv:div:0505"}
PERIODS = {
    "1916-1940 (before the Compact took effect)": (1916, 1940),
    "1941-1950": (1941, 1950),
    "1951-1956 (drought years)": (1951, 1956),
    "1957-1978": (1957, 1978),
    "1951-1978 (the low era)": (1951, 1978),
    "1979-1999": (1979, 1999),
    "1991-2020 (the site's normal)": (1991, 2020),
    "2000-2025": (2000, 2025),
}


def flow(con, uids: list[str]) -> pd.DataFrame:
    d = read_daily(con, uids, START, END)
    if d.empty:
        return pd.DataFrame(columns=["date", "cfs"])
    d = d.assign(gauge="g", source=d["site_uid"].str.split(":").str[0])
    return pick_copy(d)[["date", "cfs"]]


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    con.execute("SET memory_limit='6GB'; SET threads=3; SET TimeZone='UTC'")
    f = {k: flow(con, v) for k, v in GAUGES.items()}
    inflow = hc.san_marcial_inflow(f["sm_main"], f["floodway"], f["channel"])

    t = hc.annual_af(f["otowi"]).rename(columns={"af": "otowi_af", "days": "otowi_days"})
    for name, frame in (("san_marcial", inflow), ("release", f["release"]), ("caballo_release", f["caballo_release"]),
                        *((k, f[k]) for k in ("del_norte", "conejos", "lobatos", "embudo", "chamita"))):
        t = t.merge(hc.annual_af(frame).rename(columns={"af": f"{name}_af", "days": f"{name}_days"}), on="wy", how="outer")

    raw = res_daily(con, ["usbr_hydrodata:1119", "usace_cwms:E Butte"], ["reservoir_storage", "reservoir_area"])
    eb = splice(raw, ["usbr_hydrodata:1119", "usace_cwms:E Butte"], "reservoir_storage").rename(columns={"value": "af"})
    area = splice(raw, ["usbr_hydrodata:1119"], "reservoir_area").rename(columns={"value": "acres"})
    cab = splice(res_daily(con, ["usbr_hydrodata:1094"], ["reservoir_storage"]), ["usbr_hydrodata:1094"], "reservoir_storage").rename(columns={"value": "af"})
    s = hc.wy_storage(eb).rename(columns={"mean_af": "eb_mean_af", "end_af": "eb_end_af", "change_af": "eb_change_af", "days": "eb_days"})
    c = hc.wy_storage(cab)[["wy", "mean_af"]].rename(columns={"mean_af": "caballo_mean_af"})
    a = area.assign(wy=hc.water_year(area["date"]).values).groupby("wy")["acres"].mean().rename("eb_area_acres").reset_index()
    t = t.merge(s, on="wy", how="outer").merge(c, on="wy", how="left").merge(a, on="wy", how="left")
    t["project_mean_af"] = t["eb_mean_af"] + t["caballo_mean_af"]
    t["valley_loss_af"] = t["otowi_af"] - t["san_marcial_af"]
    t["co_index_af"] = t["del_norte_af"] + t["conejos_af"]                       # Colorado's headwater supply
    t["co_use_af"] = t["co_index_af"] - t["lobatos_af"]                          # net use in Colorado's San Luis Valley (plus valley inflow, which offsets it)
    t["nm_north_gain_af"] = t["embudo_af"] - t["lobatos_af"]                     # net gain from the state line to Embudo (tributaries less use)
    t["espanola_gain_af"] = t["otowi_af"] - t["embudo_af"] - t["chamita_af"]     # net gain from Embudo and the Chama's mouth to Otowi
    t["residual_af"] = hc.balance(t.rename(columns={"san_marcial_af": "inflow_af", "eb_change_af": "change_af"}))["residual_af"]

    ids = list(DIVISIONS.values()) + [f"nclimdiv:div:29{n:02d}" for n in range(1, 9)]
    q = ",".join(f"'{x}'" for x in ids)
    mon = con.execute(f"""select site_uid, cast(datetime_utc as date) as date, variable, value from observations
        where source='nclimdiv' and site_uid in ({q}) and variable in ('precip','pdsi','air_temp') and interval='monthly'
          and (variable <> 'air_temp' or statistic = 'mean')""").df()
    clim = hc.wy_climate(mon)
    nm = clim[clim.site_uid.str.startswith("nclimdiv:div:29")].groupby("wy").agg(precip_nm_in=("precip_in", "mean"), pdsi_nm=("pdsi", "mean"),
                                                                                 n=("precip_in", "size")).reset_index()
    t = t.merge(nm[nm.n == 8].drop(columns="n"), on="wy", how="left")
    for col, uid in DIVISIONS.items():
        one = clim[clim.site_uid == uid][["wy", "precip_in", "pdsi"]].rename(columns={"precip_in": f"precip_{col}_in", "pdsi": f"pdsi_{col}"})
        t = t.merge(one, on="wy", how="left")

    # Other people's figures, from the local SOURCES folder only: Compact balances on 31 December (our transcription of the Commission's reports)
    # and the Project's allotment per acre (USGS data release 10.5066/P9J9NYND). Both are calendar years; they are joined to the water year that
    # ends that September, which is the closest match and is said so in the report.
    SOURCES.mkdir(parents=True, exist_ok=True)
    cb_path, al_path = SOURCES / "compact_balances.csv", SOURCES / "Allotments_and_Allocations.csv"
    if cb_path.exists():
        cb = pd.read_csv(cb_path)
        signed = cb.assign(v=cb.acre_feet.where(cb.status != "credit", -cb.acre_feet))
        piv = signed.pivot_table(index="year", columns="account", values="v", aggfunc="first")
        piv = piv.rename(columns={"Colorado": "compact_debit_co_af", "New Mexico": "compact_debit_nm_af", "Project storage": "project_storage_dec31_af"})
        t = t.merge(piv.reset_index().rename(columns={"year": "wy"}), on="wy", how="left")
    else:
        print(f"no {cb_path}: Compact balances left out (transcribe them from the reports linked in references.md)")
    if not al_path.exists():
        urllib.request.urlretrieve(ALLOTMENTS_URL, al_path)
    al = pd.read_csv(al_path).rename(columns={"Year": "wy", "Allotment to Lands": "allotment_ft_per_acre",
                                              "Diversion Allocation Total": "allocation_total_af"})[["wy", "allotment_ft_per_acre", "allocation_total_af"]]
    t = t.merge(al, on="wy", how="left")

    # Seasons: snow season (November-April) precipitation makes the river; July-September monsoon rain mostly does not. Melt-season temperature.
    for col, uid in (("co_rg", "nclimdiv:div:0505"), ("nm_mtn", "nclimdiv:div:2902")):
        one = mon[mon.site_uid == uid]
        for name, var, months, how in (("snow_season_in", "precip", [11, 12, 1, 2, 3, 4], "sum"), ("monsoon_in", "precip", [7, 8, 9], "sum"),
                                       ("melt_season_c", "air_temp", [3, 4, 5, 6], "mean")):
            v = hc.seasonal(one, var, months, how)[["wy", "value"]].rename(columns={"value": f"{name.rsplit('_', 1)[0]}_{col}_{name.rsplit('_', 1)[1]}"})
            t = t.merge(v, on="wy", how="left")

    t = t[(t.wy >= 1896) & (t.wy <= 2025)].sort_values("wy").reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    t.round(1).to_csv(SOURCES / "elephant-butte-with-sources.csv", index=False)
    t.drop(columns=[c for c in THIRD_PARTY if c in t]).round(1).to_csv(OUT / "elephant-butte.csv", index=False)
    cols = ["otowi_af", "san_marcial_af", "valley_loss_af", "release_af", "caballo_release_af", "eb_mean_af", "project_mean_af",
            "eb_area_acres", "residual_af", "precip_nm_in", "pdsi_nm", "precip_nm_mtn_in", "precip_co_rg_in", "pdsi_co_rg",
            "snow_season_co_rg_in", "monsoon_co_rg_in", "melt_season_co_rg_c", "snow_season_nm_mtn_in", "monsoon_nm_mtn_in", "melt_season_nm_mtn_c",
            "del_norte_af", "conejos_af", "co_index_af", "lobatos_af", "co_use_af", "embudo_af", "nm_north_gain_af", "chamita_af", "espanola_gain_af"]
    hc.period_summary(t, PERIODS, cols).round(1).to_csv(OUT / "elephant-butte-periods.csv", index=False)
    print(f"wrote {OUT / 'elephant-butte.csv'} ({len(t)} water years), elephant-butte-periods.csv and {SOURCES / 'elephant-butte-with-sources.csv'}")


if __name__ == "__main__":
    main()
