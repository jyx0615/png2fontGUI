/**
 * Font generation pipeline orchestrator — ported from Python pipeline.py
 * Runs the 10-step pipeline with status updates and heartbeat.
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
import { GenerateFontParams, JobLifecycleStatus } from "./types.js";
import { HEARTBEAT_SECONDS } from "./constants.js";
import { runFontForge } from "./subprocess/fontforge.js";
import { runAddsvg } from "./subprocess/addsvg.js";
import { runMaximumColor } from "./subprocess/maximumColor.js";
import { runTtf2Woff2 } from "./subprocess/ttf2woff2.js";
import { runAddSbixTable, runDropUnusedTables } from "./subprocess/fontTablesCli.js";
import { runPng2SvgTrace, runPng2SvgShift, runPng2SvgFlatten } from "./subprocess/png2svgCli.js";

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
  const buildDir = join(tempDir, "build");

  mkdirSync(svgFolder, { recursive: true });

  // Compute vertical metrics
  const { ascent, descent, lineHeight } = verticalMetrics(params.upm);
  const finalLineHeight = params.lineHeight ?? lineHeight;

  let heartbeatInterval: NodeJS.Timeout | null = null;

  console.log(`[job ${jobId}] starting pipeline (fontname=${params.fontname}, upm=${params.upm})`);

  try {
    // Start heartbeat thread
    heartbeatInterval = setInterval(() => {
      writeJobStatus(jobId, {});
    }, HEARTBEAT_SECONDS * 1000);

    // Step 1: Trace PNGs to SVG
    updateStatus(jobId, "tracing", "Tracing PNGs to SVG outlines");
    let result = await runPng2SvgTrace(pngFolder, svgFolder, params.upm);
    if (result.code !== 0) {
      throw new Error(`PNG to SVG tracing failed: ${result.stderr || result.stdout}`);
    }

    // Step 2: Shift SVGs for descent
    updateStatus(jobId, "shifting", "Applying vertical metrics to traced SVGs");
    result = await runPng2SvgShift(svgFolder, svgShiftedFolder, params.upm, descent);
    if (result.code !== 0) {
      throw new Error(`SVG shift failed: ${result.stderr || result.stdout}`);
    }

    // Step 3: Flatten SVGs for FontForge
    updateStatus(jobId, "flattening", "Flattening SVGs to silhouettes for FontForge");
    result = await runPng2SvgFlatten(svgShiftedFolder, svgOutlineFolder);
    if (result.code !== 0) {
      throw new Error(`SVG flatten failed: ${result.stderr || result.stdout}`);
    }

    // Step 4: Generate base TTF with FontForge
    updateStatus(jobId, "fontforge", "Compiling TTF with FontForge");
    const outputTtf = join(tempDir, `${params.fontname}.ttf`);
    result = await runFontForge(
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
    );
    if (result.code !== 0) {
      throw new Error(`FontForge failed: ${result.stderr || result.stdout}`);
    }

    // Step 5: Embed SVG outlines with addsvg (non-fatal)
    updateStatus(jobId, "svg-embed", "Embedding SVG outlines into TTF");
    result = await runAddsvg(svgShiftedFolder, outputTtf);
    if (result.code !== 0) {
      console.warn(`[job ${jobId}] addsvg failed (non-fatal): ${result.stderr || result.stdout}`);
    }

    // Step 6: Generate COLR table with nanoemoji
    updateStatus(jobId, "color-optimize", "Embedding color layers (nanoemoji)");
    const colorResult = await runMaximumColor(outputTtf, tempDir, jobId);
    const outputTtfColor = join(tempDir, `${params.fontname}_color.ttf`);
    if (!colorResult.success) {
      console.warn(`[job ${jobId}] nanoemoji maximum_color failed (fallback to non-color TTF): ${colorResult.stderr}`);
      copyFileSync(outputTtf, outputTtfColor);
    } else {
      copyFileSync(colorResult.outputPath, outputTtfColor);
    }

    // Step 7: Add sbix table (non-fatal)
    result = await runAddSbixTable(outputTtfColor, buildDir, outputTtf);
    if (result.code !== 0) {
      console.warn(`[job ${jobId}] add-sbix failed (non-fatal): ${result.stderr || result.stdout}`);
    }

    // Step 8: Drop unused tables for TTF flavor
    result = await runDropUnusedTables(outputTtfColor, "ttf");
    if (result.code !== 0) {
      console.warn(`[job ${jobId}] drop-tables for TTF failed (non-fatal): ${result.stderr || result.stdout}`);
    }

    // Step 9: Convert to WOFF2
    updateStatus(jobId, "woff", "Converting TTF to WOFF2");
    const outputWoff2 = join(tempDir, `${params.fontname}.woff2`);
    result = await runTtf2Woff2(outputTtfColor, outputWoff2);
    if (result.code !== 0) {
      console.warn(`[job ${jobId}] ttf2woff2 failed: ${result.stderr}`);
      // Continue anyway — TTF is still usable
    } else {
      // Drop unused tables for WOFF2 flavor
      result = await runDropUnusedTables(outputWoff2, "woff2");
      if (result.code !== 0) {
        console.warn(`[job ${jobId}] drop-tables for WOFF2 failed (non-fatal): ${result.stderr || result.stdout}`);
      }
    }

    // Step 10: Create ZIP file with TTF and WOFF2
    updateStatus(jobId, "zipping", "Packaging TTF + WOFF2");
    const zipFilename = `${params.fontname}_fonts.zip`;
    const zipPath = join(tempDir, zipFilename);
    await createZipArchive(zipPath, [
      { file: outputTtfColor, name: `${params.fontname}.ttf` },
      { file: outputWoff2, name: `${params.fontname}.woff2` },
    ]);

    // Step 11: Mark as completed
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

function updateStatus(jobId: string, phase: string, detail: string, zipFilename?: string): void {
  const status: Partial<Record<string, unknown>> = {
    status: "processing",
    phase,
    detail,
  };
  if (zipFilename) {
    status.status = "completed";
    status.zip_filename = zipFilename;
  }
  console.log(`[job ${jobId}] phase=${phase}${detail ? ` — ${detail}` : ""}`);
  writeJobStatus(jobId, status as any);
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
