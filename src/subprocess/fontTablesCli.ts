/**
 * font_tables.py CLI wrapper — invokes the Python drop-tables subcommand for
 * TTF post-processing (best-effort and non-fatal).
 */

import { runProcess } from "./runProcess.js";
import { PYTHON_BIN } from "./toolPaths.js";
import { RunProcessResult } from "../types.js";

export async function runDropUnusedTables(fontPath: string, flavor: "ttf" | "woff2"): Promise<RunProcessResult> {
  return runProcess(PYTHON_BIN, [
    "python/font_tables.py",
    "drop-tables",
    "--font-path",
    fontPath,
    "--flavor",
    flavor,
  ]);
}
