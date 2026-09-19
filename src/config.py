"""
Central configuration for the Cincinnati 311 service performance project.

Everything that could change between runs lives here, not scattered through
the scripts. If a number or a name appears in more than one script, it belongs
in this file.

WHY THIS MATTERS: a reviewer should be able to read one short file and know
exactly which data was pulled, for which window, from which source. If these
values are buried inside scripts, the project is not reproducible and you
cannot defend a number in an interview.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"          # immutable snapshots, never edited by hand
INTERIM_DIR = DATA_DIR / "interim"  # typed / cleaned, created in step 2
WAREHOUSE = DATA_DIR / "warehouse.duckdb"  # built in step 4
REPORTS_DIR = PROJECT_ROOT / "reports"     # validation logs, metric dictionary

for _d in (RAW_DIR, INTERIM_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Source system
# ---------------------------------------------------------------------------
# The City of Cincinnati open data portal runs on Socrata. Every dataset has a
# four-four identifier (for example gcej-gmiw) that appears in its URL.
SOCRATA_DOMAIN = "data.cincinnati-oh.gov"

# Optional. Anonymous requests are throttled more aggressively than
# token-authenticated ones. Register a free app token on the portal and set it
# as an environment variable named SOCRATA_APP_TOKEN. The project works without
# one, just more slowly.
APP_TOKEN_ENV_VAR = "SOCRATA_APP_TOKEN"

DATASETS = {
    # key -> (four-four id, human label used in filenames and the manifest)
    "service_requests": ("gcej-gmiw", "Cincinnati 311 Non-Emergency Service Requests"),
    # Added in step 6. Confirm the four-four id from the portal before use.
    # "csr_survey": ("XXXX-XXXX", "Cincinnati CSR Satisfaction Survey"),
}

# ---------------------------------------------------------------------------
# Snapshot window
# ---------------------------------------------------------------------------
# The source refreshes daily. Without a fixed window and a recorded pull date,
# your case study numbers silently change every time you rerun anything.
WINDOW_START = "2023-01-01"  # inclusive
WINDOW_END = "2026-08-31"    # inclusive; keep to complete months only

# Filled in after running discover.py. Leave as None until the real column
# name is confirmed against the live dataset. Guessing here is how projects
# end up silently filtering on the wrong field.
CREATED_DATE_FIELD = "date_created"   # confirmed via src.discover, 2026-09-18
ORDER_FIELD = ":id"         # Socrata internal row id; stable for pagination

# ---------------------------------------------------------------------------
# Fetch behaviour
# ---------------------------------------------------------------------------
PAGE_SIZE = 50_000     # rows per API request
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 3
REQUEST_TIMEOUT = 120
