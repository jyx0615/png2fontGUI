/**
 * Disk-backed job store — ported from Python job_store.py
 * Stores job status in status.json per job directory, with atomic writes.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync, statSync, rmSync } from "fs";
import { join } from "path";
import { JOBS_ROOT, JOB_TTL_SECONDS, ORPHAN_STALE_SECONDS, JOB_ID_RE } from "./constants.js";
import { JobStatus, JobLifecycleStatus } from "./types.js";

// Per-job lock: Map<jobId, Promise> to serialize concurrent writes (heartbeat + main pipeline)
const perJobLocks = new Map<string, Promise<void>>();

/**
 * Gets the job directory path.
 */
export function jobDir(jobId: string): string {
  return join(JOBS_ROOT, jobId);
}

/**
 * Creates a promise-chain lock for a specific job to serialize writes.
 */
function getJobLock(jobId: string): Promise<void> {
  const existing = perJobLocks.get(jobId) ?? Promise.resolve();
  return existing;
}

/**
 * Acquires and holds a lock for exclusive access to a job's status.json.
 * Returns a function to release the lock.
 */
function acquireJobLock(jobId: string): () => void {
  let releaseLock: () => void = () => {};

  const lockPromise = getJobLock(jobId).then(
    () =>
      new Promise<void>((resolve) => {
        releaseLock = resolve;
      })
  );

  perJobLocks.set(jobId, lockPromise);
  return releaseLock;
}

/**
 * Writes job status to status.json, merging fields (not replacing).
 * Atomic write via temp file + rename, using synchronous fs calls.
 * Serialized per-job to avoid heartbeat callback interleaving with main pipeline writes.
 */
export function writeJobStatus(jobId: string, fields: Partial<JobStatus>): void {
  const release = acquireJobLock(jobId);

  try {
    const dir = jobDir(jobId);
    mkdirSync(dir, { recursive: true });

    const statusPath = join(dir, "status.json");
    const current = readJobStatus(jobId) ?? { status: "queued" as JobLifecycleStatus };

    const updated = {
      ...current,
      ...fields,
      updated_at: Math.floor(Date.now() / 1000), // epoch seconds
    } as JobStatus;

    const tmpPath = `${statusPath}.tmp`;
    writeFileSync(tmpPath, JSON.stringify(updated));
    renameSync(tmpPath, statusPath);
  } finally {
    release();
  }
}

/**
 * Reads job status from status.json.
 * Returns null if the file doesn't exist or can't be parsed.
 */
export function readJobStatus(jobId: string): JobStatus | null {
  try {
    const statusPath = join(jobDir(jobId), "status.json");
    const content = readFileSync(statusPath, "utf-8");
    return JSON.parse(content);
  } catch {
    return null;
  }
}

/**
 * Deletes job workspaces older than the TTL.
 * Called on every new job submission.
 */
export function sweepStaleJobs(): void {
  if (!existsSync(JOBS_ROOT)) {
    return;
  }

  const cutoffTime = Math.floor(Date.now() / 1000) - JOB_TTL_SECONDS;

  try {
    const entries = readdirSync(JOBS_ROOT);
    for (const entry of entries) {
      const path = join(JOBS_ROOT, entry);
      try {
        const stat = statSync(path);
        if (stat.isDirectory() && stat.mtimeMs / 1000 < cutoffTime) {
          rmSync(path, { recursive: true });
        }
      } catch {
        // Ignore errors for individual entries (e.g. permission denied)
      }
    }
  } catch {
    // Ignore errors iterating JOBS_ROOT
  }
}

/**
 * Marks jobs with stale heartbeats (dead worker threads) as failed.
 * A live worker heartbeats updated_at every HEARTBEAT_SECONDS,
 * so non-terminal jobs with stale updated_at have no thread behind them.
 * Called at startup and inline in status checks.
 */
export function failOrphanedJobs(): void {
  if (!existsSync(JOBS_ROOT)) {
    return;
  }

  const cutoffTime = Math.floor(Date.now() / 1000) - ORPHAN_STALE_SECONDS;

  try {
    const entries = readdirSync(JOBS_ROOT);
    for (const jobId of entries) {
      if (!JOB_ID_RE.test(jobId)) {
        continue;
      }

      const status = readJobStatus(jobId);
      if (
        status &&
        (status.status === "queued" || status.status === "processing") &&
        (status.updated_at ?? 0) < cutoffTime
      ) {
        writeJobStatus(jobId, {
          status: "failed",
          phase: "error",
          detail: "The font server restarted during generation — please export again.",
        });
      }
    }
  } catch {
    // Ignore errors
  }
}
