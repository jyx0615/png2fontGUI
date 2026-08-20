/**
 * POST /api/generate-font handler — accepts PNG uploads and starts a font generation job
 */

import { Router, Request, Response } from "express";
import multer from "multer";
import { randomBytes } from "crypto";
import { join } from "path";
import { writeFileSync, mkdirSync } from "fs";
import { sweepStaleJobs, writeJobStatus, jobDir } from "../jobStore.js";
import { JOB_ID_RE } from "../constants.js";
import { runGenerationJob } from "../pipeline.js";
import { GenerateFontParams } from "../types.js";

const router = Router();

// Configure multer for in-memory file handling
const upload = multer({ storage: multer.memoryStorage() });

router.post("/api/generate-font", upload.array("files"), async (req: Request, res: Response) => {
  try {
    // Validate files are PNG
    const files = req.files as Express.Multer.File[];
    if (!files || files.length === 0) {
      return res.status(400).json({ detail: "No files uploaded" });
    }

    for (const file of files) {
      if (!file.originalname.toLowerCase().endsWith(".png")) {
        return res.status(400).json({
          detail: `Invalid file format: ${file.originalname}. Only PNG files are supported.`,
        });
      }
    }

    // Sweep stale jobs before creating new one
    sweepStaleJobs();

    // Generate job ID
    const jobId = randomBytes(16).toString("hex");
    if (!JOB_ID_RE.test(jobId)) {
      return res.status(500).json({ detail: "Failed to generate valid job ID" });
    }

    // Create job directory and save files
    const jobDirPath = jobDir(jobId);
    const pngFolder = join(jobDirPath, "png_glyphs");
    mkdirSync(pngFolder, { recursive: true });

    for (const file of files) {
      const filename = file.originalname || "glyph.png";
      const filepath = join(pngFolder, filename);
      writeFileSync(filepath, file.buffer);
    }

    // Parse form parameters
    const params: GenerateFontParams = {
      fontname: String(req.body.fontname ?? "MyCustomFont"),
      fullname: String(req.body.fullname ?? "My Custom Font"),
      familyname: String(req.body.familyname ?? "My Family"),
      upm: Number(req.body.upm ?? 1000),
      advanceWidth: Number(req.body.advance_width ?? 600),
      verticalRaise: Number(req.body.vertical_raise ?? 0),
      monospace: req.body.monospace === "true" || req.body.monospace === true,
      lineHeight: req.body.line_height ? Number(req.body.line_height) : null,
      letterSpacing: Number(req.body.letter_spacing ?? 0),
    };

    // Write initial status and kick off pipeline
    writeJobStatus(jobId, { status: "queued", phase: "queued", detail: "Waiting to start" });

    // Fire-and-forget: do NOT await this
    void runGenerationJob(jobId, params);

    return res.status(202).json({ job_id: jobId, status: "queued" });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error("POST /api/generate-font error:", message);
    return res.status(500).json({ detail: "Internal server error" });
  }
});

export default router;
