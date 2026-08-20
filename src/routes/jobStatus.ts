/**
 * GET /api/job/:id handler — returns job status including phase and progress detail
 */

import { Router, Request, Response } from "express";
import { readJobStatus, failOrphanedJobs } from "../jobStore.js";
import { JOB_ID_RE } from "../constants.js";

const router = Router();

router.get("/api/job/:id", (req: Request, res: Response) => {
  try {
    const jobId = req.params.id;

    if (!JOB_ID_RE.test(jobId)) {
      return res.status(400).json({ detail: "Invalid job ID format" });
    }

    // Check for orphaned jobs and fail them if needed
    failOrphanedJobs();

    const status = readJobStatus(jobId);
    if (!status) {
      return res.status(404).json({ detail: `Job ${jobId} not found` });
    }

    return res.status(200).json(status);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("GET /api/job/:id error:", message);
    return res.status(500).json({ detail: "Internal server error" });
  }
});

export default router;
