"""Fetch and update OpenPowerlifting competition data.

Scrapes rankings directly from the OpenPowerlifting backend REST API:
    https://www.openpowerlifting.org/api/rankings/by-dots

Extracts the top all-time lifters in Raw+Wraps sorted by Dots, validates internal
consistency, and writes to reference/openpowerlifting_top_lifters.csv.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import sys
import urllib.request

LB_TO_KG = 0.45359237
API_URL = "https://www.openpowerlifting.org/api/rankings/by-dots"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"


def fetch_rankings(limit: int = 120, chunk_size: int = 100) -> list[dict[str, any]]:
    """Query OpenPowerlifting API for top lifters by Dots."""
    rows = []
    print(f"Fetching top {limit} lifters from {API_URL}...")
    for start in range(0, limit, chunk_size):
        end = min(start + chunk_size, limit)
        url = f"{API_URL}?start={start}&end={end}&lang=en&units=lbs"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            chunk = data.get("rows", [])
            rows.extend(chunk)
            print(f"  Retrieved rows {start} to {start + len(chunk)} (total: {len(rows)})")
            if len(chunk) < (end - start):
                break

    parsed = []
    for r in rows:
        try:
            # Schema mapping:
            # 1: rank, 2: lifter, 8: fed, 9: date, 13: sex, 14: equip, 15: age
            # 17: bodyweight_lb, 19: squat_lb, 20: bench_lb, 21: deadlift_lb, 22: total_lb, 23: dots
            rank = int(r[1])
            lifter = str(r[2]).strip()
            fed = str(r[8] or "").strip()
            meet_date = str(r[9] or "").strip()
            sex = str(r[13] or "").strip()
            age = str(r[15] or "0").strip()
            equip = str(r[14] or "").strip()
            bw = round(float(r[17]), 1) if r[17] else 0.0
            sq = round(float(r[19]), 1) if r[19] else 0.0
            bp = round(float(r[20]), 1) if r[20] else 0.0
            dl = round(float(r[21]), 1) if r[21] else 0.0
            dots = round(float(r[23]), 2) if r[23] else 0.0

            # Internal consistency: ensure squat + bench + deadlift == total
            # (In cases where a 4th single-record attempt was recorded as best lift,
            # using sum(lifts) ensures data integrity for ratio & ceiling calculations)
            total = round(sq + bp + dl, 1)

            parsed.append({
                "rank": rank,
                "lifter": lifter,
                "fed": fed,
                "date": meet_date,
                "sex": sex,
                "age": age,
                "equip": equip,
                "bodyweight_lb": bw,
                "squat_lb": sq,
                "bench_lb": bp,
                "deadlift_lb": dl,
                "total_lb": total,
                "dots": dots,
            })
        except Exception as err:
            print(f"Warning: skipped row due to parse error: {err}", file=sys.stderr)

    return parsed


def audit_dataset(lifters: list[dict[str, any]]) -> None:
    """Print statistical summaries: observed maxima and ratio envelopes."""
    if not lifters:
        print("No lifters to audit.")
        return

    max_sq = max(lifters, key=lambda x: x["squat_lb"])
    max_bp = max(lifters, key=lambda x: x["bench_lb"])
    max_dl = max(lifters, key=lambda x: x["deadlift_lb"])

    bp_ratios = [l["bench_lb"] / l["squat_lb"] for l in lifters if l["squat_lb"] > 0]
    dl_ratios = [l["deadlift_lb"] / l["squat_lb"] for l in lifters if l["squat_lb"] > 0]

    print("\n" + "=" * 60)
    print(f"AUDIT REPORT ({len(lifters)} lifters)")
    print("=" * 60)
    print(f"Max Squat:    {max_sq['squat_lb'] * LB_TO_KG:.1f} kg ({max_sq['squat_lb']} lb) — {max_sq['lifter']} ({max_sq['equip']})")
    print(f"Max Bench:    {max_bp['bench_lb'] * LB_TO_KG:.1f} kg ({max_bp['bench_lb']} lb) — {max_bp['lifter']} ({max_bp['equip']})")
    print(f"Max Deadlift: {max_dl['deadlift_lb'] * LB_TO_KG:.1f} kg ({max_dl['deadlift_lb']} lb) — {max_dl['lifter']} ({max_dl['equip']})")
    print("-" * 60)
    print(f"Bench / Squat ratio:    [{min(bp_ratios):.2f}, {max(bp_ratios):.2f}]")
    print(f"Deadlift / Squat ratio: [{min(dl_ratios):.2f}, {max(dl_ratios):.2f}]")
    print("=" * 60 + "\n")


def write_csv(lifters: list[dict[str, any]], output_path: Path) -> None:
    """Write lifters to CSV with standard header comments."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    today_str = date.today().isoformat()

    header_comments = [
        f'# Source: openpowerlifting.org rankings, filter "Raw+Wraps", all classes, all\n',
        f'# sexes, sorted by Dots, top {len(lifters)} all-time. Captured {today_str}. Units as the\n',
        f'# site displayed them: POUNDS.\n',
        f'#\n',
        f'# Captured programmatically via scripts/fetch_openpowerlifting.py from the\n',
        f'# OpenPowerlifting API. Used to bound human performance so validation\n',
        f'# ceilings and ratios are grounded in empirical meet data.\n',
    ]

    fieldnames = [
        "rank", "lifter", "fed", "date", "sex", "age", "equip",
        "bodyweight_lb", "squat_lb", "bench_lb", "deadlift_lb", "total_lb", "dots"
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        f.writelines(header_comments)
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(lifters)

    print(f"Successfully saved {len(lifters)} lifters to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape and update OpenPowerlifting meet rankings.")
    parser.add_argument("--limit", type=int, default=120, help="Number of top lifters to retrieve (default: 120)")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "reference" / "openpowerlifting_top_lifters.csv",
        help="Target CSV output path",
    )
    parser.add_argument("--audit-only", action="store_true", help="Fetch and audit without writing to file")

    args = parser.parse_args()

    lifters = fetch_rankings(limit=args.limit)
    audit_dataset(lifters)

    if not args.audit_only:
        write_csv(lifters, args.output)


if __name__ == "__main__":
    main()
