/**
 * font_tables.py CLI wrapper — invokes the Python drop-tables subcommand for
 * TTF post-processing (best-effort and non-fatal).
 */

import { runProcess } from "./runProcess.js";
import { PYTHON_BIN } from "./toolPaths.js";

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
