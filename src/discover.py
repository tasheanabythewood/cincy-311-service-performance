"""
Step 1a. Look at the dataset before pulling it.

Run this first, every time you add a new source. It answers three questions
that decide everything downstream:

  1. What are the real column names? (You cannot filter on a field you guessed.)
  2. What does a real row look like? (Date formats, casing, code values.)
  3. How many rows match the window you intend to pull?

WHY NOT SKIP THIS: the most common way an analysis goes quietly wrong is
filtering on the wrong date column. A service request has several dates:
when it was created, when it was last updated, when it was closed, and when
it was due. Filtering "2023 onward" on the closed date silently drops every
request that is still open, which is exactly the backlog you are trying to
measure. The bug produces a clean-looking dashboard with a wrong answer.

Usage:
    python -m src.discover
    python -m src.discover --dataset service_requests
"""

from __future__ import annotations

import argparse

import pandas as pd

from . import config, socrata


def describe(dataset_key: str) -> None:
    dataset_id, label = config.DATASETS[dataset_key]
    print("=" * 72)
    print(f"{label}")
    print(f"dataset id : {dataset_id}")
    print(f"source     : https://{config.SOCRATA_DOMAIN}/resource/{dataset_id}.csv")
    print("=" * 72)

    columns = socrata.get_columns(dataset_id)
    print(f"\n{len(columns)} columns:\n")
    for i, column in enumerate(columns, start=1):
        print(f"  {i:>3}. {column}")

    print("\nFirst 5 rows (all values shown as text):\n")
    sample = socrata.get_sample(dataset_id, n=5)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(sample.to_string(index=False))

    print("\nDate-like columns to review (name contains 'date' or 'time'):\n")
    date_like = [c for c in columns if "date" in c.lower() or "time" in c.lower()]
    for column in date_like:
        print(f"  {column}")
    if not date_like:
        print("  none found by name; inspect the sample above manually")

    print(
        "\nNEXT: pick the column that records when the request was CREATED, "
        "then set CREATED_DATE_FIELD in src/config.py to that exact name."
    )


def count_in_window(dataset_key: str) -> None:
    """Ask the API how many rows match the configured window, before downloading."""
    if config.CREATED_DATE_FIELD is None:
        print("\nCREATED_DATE_FIELD is not set yet, so the window count is skipped.")
        return

    dataset_id, _ = config.DATASETS[dataset_key]
    field = config.CREATED_DATE_FIELD
    where = (
        f"{field} >= '{config.WINDOW_START}T00:00:00.000' "
        f"AND {field} <= '{config.WINDOW_END}T23:59:59.999'"
    )
    response = socrata._get(
        socrata._resource_url(dataset_id),
        {"$select": "count(1) AS n", "$where": where},
    )
    print(f"\nRows matching {config.WINDOW_START} to {config.WINDOW_END}: {response.text.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="service_requests", choices=list(config.DATASETS))
    args = parser.parse_args()

    describe(args.dataset)
    count_in_window(args.dataset)


if __name__ == "__main__":
    main()
