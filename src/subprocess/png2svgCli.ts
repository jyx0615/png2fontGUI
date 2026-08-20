/**
 * png2svg.py CLI wrapper — invokes Python subcommands for PNG->SVG processing
 */

import { runProcess } from "./runProcess.js";
import { PYTHON_BIN } from "./toolPaths.js";
import { RunProcessResult } from "../types.js";

export async function runPng2SvgTrace(pngFolder: string, svgOutput: string, targetUpm: number): Promise<RunProcessResult> {
  return runProcess(PYTHON_BIN, [
    "python/png2svg.py",
    "trace",
    "--png-folder",
    pngFolder,
    "--svg-output",
    svgOutput,
    "--target-upm",
    String(targetUpm),
  ]);
}

export async function runPng2SvgShift(svgFolder: string, outFolder: string, targetUpm: number, descent: number): Promise<RunProcessResult> {
  return runProcess(PYTHON_BIN, [
    "python/png2svg.py",
    "shift",
    "--svg-folder",
    svgFolder,
    "--out-folder",
    outFolder,
    "--target-upm",
    String(targetUpm),
    "--descent",
    String(descent),
  ]);
}

export async function runPng2SvgFlatten(svgFolder: string, outFolder: string): Promise<RunProcessResult> {
  return runProcess(PYTHON_BIN, [
    "python/png2svg.py",
    "flatten",
    "--svg-folder",
    svgFolder,
    "--out-folder",
    outFolder,
  ]);
}
