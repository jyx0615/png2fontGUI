/**
 * Tool binary path resolution — env-var driven with fallbacks.
 * Mirrors pipeline.py's shutil.which() + hardcoded fallback pattern.
 */

import { execSync } from "child_process";
import { existsSync } from "fs";
import { join } from "path";
import { homedir } from "os";

/**
 * Finds a binary on PATH or returns a fallback path.
 * Tries `which` command first, then checks if the fallback path exists.
 */
function resolveBinaryPath(binaryName: string, fallbackPath: string): string {
  const envVar = process.env[`${binaryName.toUpperCase()}_BIN`];
  if (envVar) {
    return envVar;
  }

  try {
    const path = execSync(`which ${binaryName}`, { encoding: "utf-8" }).trim();
    if (path) {
      return path;
    }
  } catch {
    // Binary not found on PATH
  }

  if (existsSync(fallbackPath)) {
    return fallbackPath;
  }

  // Return the binary name and hope it's on PATH
  return binaryName;
}

export const FONTFORGE_BIN =
  process.env.FONTFORGE_BIN ?? "fontforge";

export const ADDSVG_BIN =
  process.env.ADDSVG_BIN ??
  resolveBinaryPath("addsvg", "/opt/miniconda3/envs/genFontAPI/bin/addsvg");

export const MAXIMUM_COLOR_BIN =
  process.env.MAXIMUM_COLOR_BIN ??
  resolveBinaryPath("maximum_color", "/opt/miniconda3/envs/genFontAPI/bin/maximum_color");

export const PYTHON_BIN =
  process.env.PYTHON_BIN ??
  resolveBinaryPath("python3", "python3");

export const TTF2WOFF2_BIN =
  process.env.TTF2WOFF2_BIN ??
  resolveBinaryPath("ttf2woff2", join(homedir(), ".nvm/versions/node/v24.15.0/bin/ttf2woff2"));

// Note: svgcleaner and resvg are invoked only from inside Python scripts,
// so their paths aren't resolved here — they stay entirely Python-internal.
