# New Mexico Water reports

Researched reports behind [newmexicowater.org](https://newmexicowater.org): what happened to a river, reservoir or aquifer and why, from
sources that were opened and read, checked against the numbers in the nmwater archive.


## Layout

- `history/<feature>/`: one investigation per folder:
  - `report.md`: the findings, with numbered sources.
  - `references.md`: full citations, and what each source does and does not say.
  - `events.yaml`: dated events, each with its sources. It starts with `# Not yet checked by a reviewer`, and nothing in it is published until a reviewer removes that line.
  - `sources/`: figures transcribed from documents (with how each was read).
  - `*.csv`: the per-year tables, written by the feature's script.
- `scripts/<feature>.py`: rebuilds a feature's tables from the nmwater archive.
- `nmreports/`: shared checks (water years, volumes, water balance, seasons). Data only; tested in `tests/`.

## Running

Lives beside `nmwater-web` in `~/projects/newmexicowater/`. Depends on the nmwater checkout at `../../water_newmexico` (an editable path dependency) and reads its DuckDB catalog.

    uv sync
    uv run pytest
    systemd-run --user --wait --pipe --collect -p MemoryMax=9G uv run python scripts/elephant_butte.py

## Rules

- Every claim traces to a named source that was actually opened and read, not a search snippet.
- Write in our own words, with no long quotations.
- Never commit papers or PDFs.
- Compare eras in acre-feet, not percent full: the reservoir capacity tables changed over time.

## Reports

- [Elephant Butte: why the lake was low from the 1950s to about 1980](history/elephant-butte/report.md)
