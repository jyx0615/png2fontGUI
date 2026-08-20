/**
 * font_tables.py CLI wrapper — invokes Python subcommands for TTF post-processing
 * (sbix grafting and table dropping are best-effort and non-fatal)
 */

import { runProcess } from "./runProcess.js";
import { PYTHON_BIN } from "./toolPaths.js";

export async function runAddSbixTable(fontPath: string, buildDir: string, sourceTtfPath: string): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return runProcess(PYTHON_BIN, [
    "font_tables.py",
    "add-sbix",
    "--font-path",
    fontPath,
    "--build-dir",
    buildDir,
    "--source-ttf-path",
    sourceTtfPath,
  ]);
}

export async function runDropUnusedTables(fontPath: string, flavor: "ttf" | "woff2"): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return runProcess(PYTHON_BIN, [
    "font_tables.py",
    "drop-tables",
    "--font-path",
    fontPath,
    "--flavor",
    flavor,
  ]);
}
