/**
 * Configuration constants for the png2font font generation service.
 */

import { tmpdir } from "os";
import { join } from "path";

export const JOBS_ROOT = join(tmpdir(), "png2font_jobs");

export const JOB_TTL_SECONDS = 2 * 60 * 60; // 2 hours

export const JOB_ID_RE = /^[a-f0-9]{32}$/;

export const HEARTBEAT_SECONDS = 15;

export const ORPHAN_STALE_SECONDS = 90;

export const PORT = Number(process.env.PORT) || 8000;

export const CORS_ORIGINS = [
  "http://localhost:3000",
  "http://127.0.0.1:3000",
  "https://localhost:8000",
  "http://127.0.0.1:8000",
  "https://fonty.cb-playground.workers.dev",
];

export const HTTP_CONFIG = {
  CONTENT_TYPE_JSON: "application/json",
} as const;
