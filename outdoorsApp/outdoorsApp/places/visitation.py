"""Monthly visitor counts for National Park Service units (NPS Visitor Use Statistics).

Public, no key. Saved per park code as the average recreation visitors for each
month over the last two full years. NPS campgrounds share their park's code, so
they get the same pattern.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from .http import request_json
from .store import connect, find_places, save_visitation

STATS_URL = "https://irmaservices.nps.gov/v3/rest/stats/visitation"


def last_full_years(count: int = 2) -> tuple[int, int]:
    end = date.today().year - 1
    return end - count + 1, end


def fetch_monthly_visitors(park_codes: list[str]) -> tuple[dict[str, list[float]], str]:
    start, end = last_full_years()
    response = request_json(STATS_URL, params={
        "unitCodes": ",".join(code.upper() for code in park_codes),
        "startMonth": 1, "startYear": start, "endMonth": 12, "endYear": end,
    }, headers={"Accept": "application/json"}, timeout=60)
    totals: dict[str, list[float]] = {}
    counts: dict[str, list[int]] = {}
    for row in response:
        code, month = row["UnitCode"].lower(), int(row["Month"]) - 1
        totals.setdefault(code, [0.0] * 12)[month] += row.get("RecreationVisitors") or 0
        counts.setdefault(code, [0] * 12)[month] += 1
    monthly = {code: [t / c if c else 0.0 for t, c in zip(totals[code], counts[code])] for code in totals}
    return monthly, f"{start}–{end}"


def update_visitation(conn: sqlite3.Connection | None = None) -> int:
    conn = conn or connect()
    codes = sorted({p.park_code for p in find_places(source=["nps", "nps_campgrounds"], limit=None, conn=conn)
                    if p.park_code})
    if not codes:
        return 0
    monthly, period = fetch_monthly_visitors(codes)
    save_visitation(conn, monthly, period)
    return len(monthly)


def crowd_levels(monthly: list[float]) -> list[int]:
    """Visitors per month -> the app's crowd scale (1 low, 2 moderate, 3 busy).

    Relative to the park's own busiest month, but a park that never gets many
    visitors can't be "busy": under 20k a month at peak caps at moderate, under
    5k caps at low.
    """
    peak = max(monthly) if monthly else 0
    if peak <= 0:
        return [1] * 12
    cap = 3 if peak >= 20_000 else 2 if peak >= 5_000 else 1
    return [min(cap, 3 if v / peak >= 0.7 else 2 if v / peak >= 0.4 else 1) for v in monthly]
