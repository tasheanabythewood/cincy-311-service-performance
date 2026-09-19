"""
Step 1b. Pull one immutable snapshot and write a manifest describing it.

Two outputs per run:

  data/raw/<key>__<snapshot_date>.csv.gz   the rows, exactly as returned
  data/raw/<key>__<snapshot_date>.manifest.json   what was pulled and how

WHY THE RAW FILE IS NEVER EDITED: every later step reads from this file and
writes somewhere else. If cleaning happens in place, you lose the ability to
answer "what did the source actually say?" That question comes up constantly,
both when you find a suspicious number and when an interviewer asks how you
handled a specific edge case.

WHY THE MANIFEST EXISTS: this source refreshes daily. A number in your case
study is only defensible if you can say which snapshot produced it. The
manifest records the dataset id, the exact filter, the pull timestamp, the
row count, the column list, and a SHA-256 hash of the file. The hash proves
the file has not changed since it was pulled. This file is small, so commit
it to git even though the data itself is ignored.

Usage:
    python -m src.ingest
    python -m src.ingest --dataset service_requests
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json

import pandas as pd

from . import config, socrata


def _sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_where() -> str:
    """Construct the server-side filter from the configured window."""
    field = config.CREATED_DATE_FIELD
    if field is None:
        raise SystemExit(
            "CREATED_DATE_FIELD is not set in src/config.py.\n"
            "Run `python -m src.discover` first, confirm the real column name, "
            "then set it. Do not guess."
        )
    return (
        f"{field} >= '{config.WINDOW_START}T00:00:00.000' "
        f"AND {field} <= '{config.WINDOW_END}T23:59:59.999'"
    )


def ingest(dataset_key: str) -> dict:
    dataset_id, label = config.DATASETS[dataset_key]
    where = build_where()
    snapshot_date = dt.date.today().isoformat()

    data_path = config.RAW_DIR / f"{dataset_key}__{snapshot_date}.csv.gz"
    manifest_path = config.RAW_DIR / f"{dataset_key}__{snapshot_date}.manifest.json"

    print(f"Pulling {label}")
    print(f"  filter : {where}")
    print(f"  target : {data_path}")

    frames = []
    total = 0
    for page_number, page in enumerate(socrata.iter_pages(dataset_id, where=where), start=1):
        total += len(page)
        frames.append(page)
        print(f"  page {page_number:>3}: {len(page):>7,} rows (running total {total:>9,})")

    if not frames:
        raise SystemExit("No rows returned. Check the window and the filter field.")

    data = pd.concat(frames, ignore_index=True)

    # Guard against the silent paging failure described in socrata.iter_pages.
    duplicate_rows = int(data.duplicated().sum())

    data.to_csv(data_path, index=False, compression="gzip")

    manifest = {
        "dataset_key": dataset_key,
        "dataset_id": dataset_id,
        "dataset_label": label,
        "source_url": f"https://{config.SOCRATA_DOMAIN}/resource/{dataset_id}.csv",
        "filter_applied": where,
        "window_start": config.WINDOW_START,
        "window_end": config.WINDOW_END,
        "created_date_field": config.CREATED_DATE_FIELD,
        "pulled_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "snapshot_date": snapshot_date,
        "row_count": int(len(data)),
        "column_count": int(data.shape[1]),
        "columns": list(data.columns),
        "fully_duplicated_rows": duplicate_rows,
        "file": data_path.name,
        "file_sha256": _sha256(data_path),
        "file_bytes": int(data_path.stat().st_size),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nWrote {len(data):,} rows x {data.shape[1]} columns")
    print(f"  data     : {data_path}")
    print(f"  manifest : {manifest_path}")
    if duplicate_rows:
        print(
            f"\n  WARNING: {duplicate_rows:,} fully duplicated rows. "
            "Investigate before trusting counts. This can indicate a paging problem."
        )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="service_requests", choices=list(config.DATASETS))
    args = parser.parse_args()
    ingest(args.dataset)


if __name__ == "__main__":
    main()
