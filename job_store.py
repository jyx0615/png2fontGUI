"""Disk-backed job store for font generation jobs.

Generation takes minutes — far longer than proxies keep a request open
(Cloudflare tunnels cut it at ~100s). POST /api/generate-font only enqueues
and returns a job_id; clients poll GET /api/job/{id} and download from
GET /api/job/{id}/result. State lives on disk (status.json per job) so it
survives --reload restarts and works with multiple workers.
"""

import json
import logging
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger("png2font-api")

JOBS_ROOT = Path(tempfile.gettempdir()) / "png2font_jobs"
JOB_TTL_SECONDS = 2 * 60 * 60  # keep results around for 2 hours
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")
HEARTBEAT_SECONDS = 15
# A processing job whose status hasn't been touched for this long has a dead
# worker thread (heartbeats refresh updated_at every HEARTBEAT_SECONDS).
ORPHAN_STALE_SECONDS = 90

# Serializes read-modify-write of status.json between the pipeline thread and
# its heartbeat thread, so a heartbeat can never resurrect a terminal status.
_status_write_lock = threading.Lock()


def job_dir(job_id: str) -> Path:
    return JOBS_ROOT / job_id


def write_job_status(job_id: str, **fields):
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    status_path = d / "status.json"
    with _status_write_lock:
        current = read_job_status(job_id) or {}
        current.update(fields)
        current["updated_at"] = time.time()
        tmp = status_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current))
        tmp.replace(status_path)


def read_job_status(job_id: str):
    try:
        return json.loads((job_dir(job_id) / "status.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def sweep_stale_jobs():
    """Delete job workspaces older than the TTL. Called on each new submission."""
    if not JOBS_ROOT.exists():
        return
    cutoff = time.time() - JOB_TTL_SECONDS
    for d in JOBS_ROOT.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                logger.info(f"Swept stale job workspace: {d.name}")
        except OSError:
            pass


def fail_orphaned_jobs():
    """Mark jobs whose worker thread died (server restart) as failed.

    A live worker heartbeats status.json every HEARTBEAT_SECONDS, so a
    non-terminal job with a stale updated_at has no thread behind it.
    Called at startup and lazily from the status endpoint."""
    if not JOBS_ROOT.exists():
        return
    cutoff = time.time() - ORPHAN_STALE_SECONDS
    for d in JOBS_ROOT.iterdir():
        if not d.is_dir():
            continue
        status = read_job_status(d.name)
        if (
            status
            and status.get("status") in ("queued", "processing")
            and status.get("updated_at", 0) < cutoff
        ):
            write_job_status(
                d.name,
                status="failed",
                phase="error",
                detail="The font server restarted during generation — please export again.",
            )
            logger.warning(f"Marked orphaned job as failed: {d.name}")
