"""Hosted entrypoint: serve the pinned snapshot; never build anything.

Streamlit Community Cloud runs this file. It puts ``src`` on the path, points the
dashboard at the serving snapshot pinned under ``serving/snapshot.json``, fetches and
verifies that snapshot once per process if it is not already present, and then runs the
explorer. A page request can read the snapshot; nothing here ingests, builds, promotes or
replays. A failed or partial download leaves no usable file, and the page says so.

Locally the same file works with a snapshot exported by ``uv run serving-snapshot export``
placed under ``data/serving`` (or named in ``ENERGY_RECONCILIATION_SERVING_SNAPSHOT``).
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from energy_reconciliation import serving

directory = Path(os.environ.get(serving.SERVING_ENV) or serving.DEFAULT_DIRECTORY)
os.environ[serving.SERVING_ENV] = str(directory)


@st.cache_resource(show_spinner=False)
def _prepare(pin: str, where: str) -> str:
    """Fetch and verify once per process. The cache holds the outcome, not a connection."""
    try:
        serving.ensure_fetched(Path(pin), Path(where))
    except Exception as error:  # noqa: BLE001 - the page reports it
        return f"{type(error).__name__}: {error}"
    return ""


manifest_present = (directory / serving.MANIFEST_NAME).is_file()
if serving.DEFAULT_PIN.is_file() and not manifest_present:
    with st.spinner("Preparing the published snapshot (one-time download)…"):
        failure = _prepare(str(serving.DEFAULT_PIN), str(directory))
    if failure:
        os.environ[serving.SERVING_ERROR_ENV] = failure

runpy.run_path(
    str(ROOT / "src/energy_reconciliation/explorer/app.py"), run_name="__main__"
)
