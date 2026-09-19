"""
DuckDB access for the project.

WHY DUCKDB: it gives you real SQL (very close to PostgreSQL) inside Python,
with no server to install and no database to administer. It reads a gzipped
CSV directly off disk, so you write SQL against your snapshot without an
import step. From step 4 onward it also holds the star schema in a single
portable file.

WHY NOT JUST PANDAS: you can do all of this in pandas, but the SQL is the
artifact that gets read in an interview and quoted on the website. A hiring
manager can follow `SELECT ... GROUP BY ...` without knowing pandas. Write
the logic in whichever is clearer, but keep the decision logic in SQL.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from . import config


def sql_path(path: Path) -> str:
    """
    Turn a filesystem path into a safe SQL string literal body.

    WHY THIS IS NEEDED: DuckDB does not accept a bound parameter (a `?`) inside
    a CREATE VIEW statement, so the path has to be written into the SQL text.
    Two things then matter on Windows:

      1. Backslashes. DuckDB accepts forward slashes on every platform, so
         normalising avoids any argument about escaping.
      2. Single quotes. A quote in a folder name would end the string literal
         early. Doubling it is the SQL-standard escape.

    Building the literal here, in one place, means no other function has to
    remember to do it.
    """
    return str(path).replace("\\", "/").replace("'", "''")


def latest_snapshot(dataset_key: str = "service_requests") -> tuple[Path, str]:
    """
    Return the most recent raw snapshot for a dataset, plus its snapshot date.

    WHY THIS IS A FUNCTION AND NOT A HARDCODED FILENAME: you will pull a fresh
    snapshot later. Every downstream step should pick up the newest one
    automatically, but still record which one it used, so a number can always
    be traced back to a specific file.
    """
    pattern = f"{dataset_key}__*.csv.gz"
    matches = sorted(config.RAW_DIR.glob(pattern))
    if not matches:
        raise SystemExit(
            f"No snapshot found matching {config.RAW_DIR / pattern}.\n"
            "Run `python -m src.ingest` first."
        )
    newest = matches[-1]
    snapshot_date = newest.stem.replace(".csv", "").split("__")[-1]
    return newest, snapshot_date


def connect(read_only_source: Path | None = None, table: str = "raw"):
    """
    Open an in-memory DuckDB connection with the raw snapshot registered.

    The snapshot is registered as a VIEW, not copied into a table. Nothing is
    written to the raw file, which keeps the immutability rule intact.

    all_varchar=true forces every column to text. WHY: DuckDB's type sniffer
    reads a sample of rows and guesses. On this dataset that guess is wrong in
    predictable ways, for example an ID column of digits becoming an integer
    and losing leading zeros. Step 2 profiles the text; step 3 decides the
    types deliberately and writes those decisions down.
    """
    source = read_only_source or latest_snapshot()[0]
    if not source.exists():
        raise SystemExit(f"Snapshot not found: {source}")

    con = duckdb.connect()
    con.execute(
        f"""
        CREATE OR REPLACE VIEW {table} AS
        SELECT * FROM read_csv(
            '{sql_path(source)}',
            all_varchar = true,
            header = true,
            compression = 'gzip'
        )
        """
    )
    return con


def connect_warehouse(source: Path | None = None, table: str = "raw"):
    """
    Open the persistent warehouse file, with the raw snapshot registered.

    WHY A FILE AND NOT MEMORY: steps 2 and 3 were read-only passes, so an
    in-memory database was enough. From step 4 the model is built once and
    queried many times, by the analysis, by a notebook, and potentially by a BI
    tool. A single .duckdb file on disk is portable and holds the whole star
    schema.

    The raw view points at an absolute path, so it only resolves on this
    machine. That is deliberate: the warehouse tables are self-contained, and
    the view exists only during the build.
    """
    source = source or latest_snapshot()[0]
    if not source.exists():
        raise SystemExit(f"Snapshot not found: {source}")

    con = duckdb.connect(str(config.WAREHOUSE))
    con.execute(
        f"""
        CREATE OR REPLACE VIEW {table} AS
        SELECT * FROM read_csv(
            '{sql_path(source)}',
            all_varchar = true,
            header = true,
            compression = 'gzip'
        )
        """
    )
    return con


def columns(con, table: str = "raw") -> list[str]:
    """Return the column names of a registered table or view."""
    return [row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()]
