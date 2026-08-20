/**
 * Font generation pipeline orchestrator — ported from Python pipeline.py
 * Runs the 9-step pipeline with status updates and heartbeat.
 */

import { copyFileSync, mkdirSync, existsSync, createWriteStream } from "fs";
import { join } from "path";
import * as ArchiverNS from "archiver";

// The published @types/archiver declares no default/callable export, but at
// runtime (Node ESM importing a CJS module) archiver's whole module.exports
// (the callable "vending" function) lands on the namespace's `default` key.
type ArchiverFactory = (format: string, options?: Record<string, unknown>) => import("archiver").Archiver;
const archiver = (ArchiverNS as unknown as { default: ArchiverFactory }).default;
import { writeJobStatus, jobDir } from "./jobStore.js";
import { verticalMetrics } from "./config.js";
import { GenerateFontParams, JobLifecycleStatus, JobStatus, RunProcessResult } from "./types.js";
import { HEARTBEAT_SECONDS } from "./constants.js";
import { runFontForge } from "./subprocess/fontforge.js";
import { runAddsvg } from "./subprocess/addsvg.js";
import { runMaximumColor } from "./subprocess/maximumColor.js";
import { runTtf2Woff2 } from "./subprocess/ttf2woff2.js";
import { runDropUnusedTables } from "./subprocess/fontTablesCli.js";
import { runPng2SvgTrace, runPng2SvgShift, runPng2SvgFlatten } from "./subprocess/png2svgCli.js";

const OK: RunProcessResult = { code: 0, stdout: "", stderr: "" };

type PhaseSeverity = "fatal" | "non-fatal";

/**
 * One entry in the pipeline: the status reported while it runs, what happens
 * on failure, and the work itself. `failureMessage` is the prefix used for
 * the `detail` string a client sees via GET /api/job/:id when a fatal phase
 * fails — kept distinct from `statusDetail` so that wording is preserved
 * independently of the in-progress message.
 */
interface Phase {
  name: string;
  statusDetail: string;
  severity: PhaseSeverity;
  failureMessage: string;
  run: () => Promise<RunProcessResult>;
}

/**
 * Main font generation pipeline, run as fire-and-forget from the HTTP handler.
 * PNG files are pre-uploaded to the job directory before this function is called.
 */
export async function runGenerationJob(jobId: string, params: GenerateFontParams): Promise<void> {
  const tempDir = jobDir(jobId);
  const pngFolder = join(tempDir, "png_glyphs");
  const svgFolder = join(tempDir, "svg_glyphs");
  const svgShiftedFolder = join(tempDir, "svg_glyphs_shifted");
  const svgOutlineFolder = join(tempDir, "svg_glyphs_outline");
  const outputTtf = join(tempDir, `${params.fontname}.ttf`);
  const outputTtfColor = join(tempDir, `${params.fontname}_color.ttf`);
  const outputWoff2 = join(tempDir, `${params.fontname}.woff2`);
  const zipFilename = `${params.fontname}_fonts.zip`;
  const zipPath = join(tempDir, zipFilename);

  mkdirSync(svgFolder, { recursive: true });

  // Compute vertical metrics
  const { ascent, descent, lineHeight } = verticalMetrics(params.upm);
  const finalLineHeight = params.lineHeight ?? lineHeight;

  const phases: Phase[] = [
    {
      name: "tracing",
      statusDetail: "Tracing PNGs to SVG outlines",
      severity: "fatal",
      failureMessage: "PNG to SVG tracing failed",
      run: () => runPng2SvgTrace(pngFolder, svgFolder, params.upm),
    },
    {
      name: "shifting",
      statusDetail: "Applying vertical metrics to traced SVGs",
      severity: "fatal",
      failureMessage: "SVG shift failed",
      run: () => runPng2SvgShift(svgFolder, svgShiftedFolder, params.upm, descent),
    },
    {
      name: "flattening",
      statusDetail: "Flattening SVGs to silhouettes for FontForge",
      severity: "fatal",
      failureMessage: "SVG flatten failed",
      run: () => runPng2SvgFlatten(svgShiftedFolder, svgOutlineFolder),
    },
    {
      name: "fontforge",
      statusDetail: "Compiling TTF with FontForge",
      severity: "fatal",
      failureMessage: "FontForge failed",
      run: () =>
        runFontForge(
          svgOutlineFolder,
          outputTtf,
          params.fontname,
          params.fullname,
          params.familyname,
          params.upm,
          params.advanceWidth,
          params.verticalRaise,
          ascent,
          descent,
          finalLineHeight,
          params.letterSpacing,
          params.monospace
        ),
    },
    {
      name: "svg-embed",
      statusDetail: "Embedding SVG outlines into TTF",
      severity: "non-fatal",
      failureMessage: "addsvg failed",
      run: () => runAddsvg(svgShiftedFolder, outputTtf),
    },
    {
      name: "color-optimize",
      statusDetail: "Embedding color layers (nanoemoji)",
      severity: "non-fatal",
      failureMessage: "color-optimize failed",
      run: () => runColorOptimizePhase(jobId, outputTtf, outputTtfColor, tempDir),
    },
    {
      name: "woff",
      statusDetail: "Converting TTF to WOFF2",
      severity: "non-fatal",
      failureMessage: "ttf2woff2 failed",
      run: () => runWoffPhase(jobId, outputTtfColor, outputWoff2),
    },
    {
      name: "zipping",
      statusDetail: "Packaging TTF + WOFF2",
      severity: "fatal",
      failureMessage: "Packaging TTF + WOFF2 failed",
      run: async () => {
        await createZipArchive(zipPath, [
          { file: outputTtfColor, name: `${params.fontname}.ttf` },
          { file: outputWoff2, name: `${params.fontname}.woff2` },
        ]);
        return OK;
      },
    },
  ];

  let heartbeatInterval: NodeJS.Timeout | null = null;

  console.log(`[job ${jobId}] starting pipeline (fontname=${params.fontname}, upm=${params.upm})`);

  try {
    // Start heartbeat thread
    heartbeatInterval = setInterval(() => {
      writeJobStatus(jobId, {});
    }, HEARTBEAT_SECONDS * 1000);

    for (const phase of phases) {
      updateStatus(jobId, phase.name, phase.statusDetail);
      const result = await phase.run();
      if (result.code !== 0) {
        const message = `${phase.failureMessage}: ${result.stderr || result.stdout}`;
        if (phase.severity === "fatal") {
          throw new Error(message);
        }
        console.warn(`[job ${jobId}] ${message} (non-fatal)`);
      }
    }

    updateStatus(jobId, "done", "", zipFilename);
    console.log(`[job ${jobId}] completed successfully (zip=${zipFilename})`);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    console.error(`[job ${jobId}] pipeline failed:`, error instanceof Error ? error.stack : error);
    writeJobStatus(jobId, {
      status: "failed" as JobLifecycleStatus,
      phase: "error",
      detail,
    });
  } finally {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval);
    }
  }
}

/** Runs nanoemoji, falling back to the uncolored TTF on failure — always non-fatal to the pipeline. */
async function runColorOptimizePhase(
  jobId: string,
  outputTtf: string,
  outputTtfColor: string,
  tempDir: string
): Promise<RunProcessResult> {
  const colorResult = await runMaximumColor(outputTtf, tempDir, jobId);
  if (!colorResult.success) {
    console.warn(`[job ${jobId}] nanoemoji maximum_color failed (fallback to non-color TTF): ${colorResult.stderr}`);
    copyFileSync(outputTtf, outputTtfColor);
  } else {
    copyFileSync(colorResult.outputPath, outputTtfColor);
  }

  const dropResult = await runDropUnusedTables(outputTtfColor, "ttf");
  if (dropResult.code !== 0) {
    console.warn(`[job ${jobId}] drop-tables for TTF failed (non-fatal): ${dropResult.stderr || dropResult.stdout}`);
  }
  return OK;
}

/** Converts to WOFF2; only runs the WOFF2 table-drop step if that conversion succeeded. */
async function runWoffPhase(jobId: string, outputTtfColor: string, outputWoff2: string): Promise<RunProcessResult> {
  const result = await runTtf2Woff2(outputTtfColor, outputWoff2);
  if (result.code !== 0) {
    return result;
  }

  const dropResult = await runDropUnusedTables(outputWoff2, "woff2");
  if (dropResult.code !== 0) {
    console.warn(`[job ${jobId}] drop-tables for WOFF2 failed (non-fatal): ${dropResult.stderr || dropResult.stdout}`);
  }
  return result;
}

function updateStatus(jobId: string, phase: string, detail: string, zipFilename?: string): void {
  const status: Partial<JobStatus> = {
    status: "processing",
    phase,
    detail,
  };
  if (zipFilename) {
    status.status = "completed";
    status.zip_filename = zipFilename;
  }
  console.log(`[job ${jobId}] phase=${phase}${detail ? ` — ${detail}` : ""}`);
  writeJobStatus(jobId, status);
}

interface FileEntry {
  file: string;
  name: string;
}

async function createZipArchive(zipPath: string, files: FileEntry[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const output = createWriteStream(zipPath);
    const archive = archiver("zip", { zlib: { level: 9 } });

    output.on("close", () => resolve());
    archive.on("error", (err: Error) => reject(err));

    archive.pipe(output);

    for (const entry of files) {
      if (existsSync(entry.file)) {
        archive.file(entry.file, { name: entry.name });
      }
    }

    archive.finalize();
  });
}
