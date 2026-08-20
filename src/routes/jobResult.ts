/**
 * GET /api/job/:id/result handler — downloads the completed zip file
 */

import { Router, Request, Response } from "express";
import { readJobStatus, jobDir } from "../jobStore.js";
import { JOB_ID_RE } from "../constants.js";
import { join } from "path";
import { existsSync } from "fs";

const router = Router();

router.get("/api/job/:id/result", (req: Request, res: Response) => {
  try {
    const jobId = req.params.id;

    if (!JOB_ID_RE.test(jobId)) {
      return res.status(400).json({ detail: "Invalid job ID format" });
    }

    const status = readJobStatus(jobId);
    if (!status) {
      return res.status(404).json({ detail: `Job ${jobId} not found` });
    }

    if (status.status !== "completed") {
      const httpStatus = status.status === "failed" ? 409 : 202;
      return res.status(httpStatus).json({
        detail: `Job ${jobId} status is ${status.status}, not completed`,
      });
    }

    if (!status.zip_filename) {
      return res.status(500).json({ detail: "Job completed but no zip filename recorded" });
    }

    const zipPath = join(jobDir(jobId), status.zip_filename);
    if (!existsSync(zipPath)) {
      return res.status(404).json({ detail: "Zip file not found on disk" });
    }

    return res.download(zipPath, status.zip_filename);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("GET /api/job/:id/result error:", message);
    return res.status(500).json({ detail: "Internal server error" });
  }
});

export default router;
