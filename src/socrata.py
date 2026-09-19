"""
A small, deliberately boring Socrata client.

It does three things:
  1. fetches the column names of a dataset
  2. fetches rows in pages, with a stable sort order
  3. retries on transient failures

WHY A CLIENT MODULE AT ALL: the alternative is clicking "Export CSV" in the
browser. That works once. It leaves no record of which filter you applied,
when you pulled it, or how many rows you got, and you cannot rerun it next
month without repeating the clicks from memory. A script is the record.
"""

from __future__ import annotations

import io
import os
import time
from typing import Iterator

import pandas as pd
import requests

from . import config


def _headers() -> dict:
    token = os.environ.get(config.APP_TOKEN_ENV_VAR)
    return {"X-App-Token": token} if token else {}


def _resource_url(dataset_id: str, fmt: str = "csv") -> str:
    return f"https://{config.SOCRATA_DOMAIN}/resource/{dataset_id}.{fmt}"


def _get(url: str, params: dict) -> requests.Response:
    """GET with bounded retries. Raises on the final failure."""
    last_error = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers=_headers(),
                timeout=config.REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                return response
            # 429 = throttled, 5xx = server side. Both are worth retrying.
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}"
            else:
                response.raise_for_status()
        except requests.RequestException as exc:
            last_error = str(exc)

        wait = config.RETRY_BACKOFF_SECONDS * attempt
        print(f"  retry {attempt}/{config.MAX_RETRIES} after {wait}s ({last_error})")
        time.sleep(wait)

    raise RuntimeError(f"Request failed after {config.MAX_RETRIES} attempts: {last_error}")


def get_columns(dataset_id: str) -> list[str]:
    """Return the column names by pulling a single row and reading the header."""
    response = _get(_resource_url(dataset_id), {"$limit": 1})
    frame = pd.read_csv(io.StringIO(response.text), dtype=str, keep_default_na=False, na_filter=False)
    return list(frame.columns)


def get_sample(dataset_id: str, n: int = 5) -> pd.DataFrame:
    """Return the first n rows as strings, for eyeballing real values."""
    response = _get(_resource_url(dataset_id), {"$limit": n})
    return pd.read_csv(io.StringIO(response.text), dtype=str, keep_default_na=False, na_filter=False)


def iter_pages(
    dataset_id: str,
    where: str | None = None,
    page_size: int | None = None,
    order: str | None = None,
) -> Iterator[pd.DataFrame]:
    """
    Yield the dataset one page at a time as string-typed DataFrames.

    WHY THE ORDER CLAUSE IS NOT OPTIONAL: paging with $limit and $offset only
    returns a correct result if the server sorts the same way on every request.
    Without an explicit stable sort, rows can be duplicated across pages or
    skipped entirely, and you will not notice, because the total row count
    still looks plausible. Sorting by the internal row id (:id) guarantees a
    stable order.

    WHY EVERYTHING IS READ AS A STRING: type inference at download time is
    lossy and silent. Leading zeros in identifiers disappear, mixed columns
    become floats, and empty strings become NaN, which erases the distinction
    between "reported as blank" and "not reported". Typing happens in step 2,
    on purpose, with the rules written down.
    """
    page_size = page_size or config.PAGE_SIZE
    order = order or config.ORDER_FIELD
    offset = 0

    while True:
        params = {"$limit": page_size, "$offset": offset, "$order": order}
        if where:
            params["$where"] = where

        response = _get(_resource_url(dataset_id), params)
        page = pd.read_csv(io.StringIO(response.text), dtype=str, keep_default_na=False, na_filter=False)

        if page.empty:
            return

        yield page

        if len(page) < page_size:
            return
        offset += page_size
