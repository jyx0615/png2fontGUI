/**
 * FontForge CLI wrapper — invokes fontforge -script font.py with SVG folder input
 */

import { runProcess } from "./runProcess.js";
import { FONTFORGE_BIN } from "./toolPaths.js";
import { RunProcessResult } from "../types.js";

export async function runFontForge(
  svgFolder: string,
  outputTtf: string,
  fontname: string,
  fullname: string,
  familyname: string,
  upm: number,
  advanceWidth: number,
  verticalRaise: number,
  ascent: number,
  descent: number,
  lineHeight: number,
  letterSpacing: number,
  monospace: boolean
): Promise<RunProcessResult> {
  const args = [
    "-script",
    "python/font.py",
    svgFolder,
    "--output",
    outputTtf,
    "--fontname",
    fontname,
    "--fullname",
    fullname,
    "--familyname",
    familyname,
    "--upm",
    String(upm),
    "--advance-width",
    String(advanceWidth),
    "--vertical-raise",
    String(verticalRaise),
    "--ascent",
    String(ascent),
    "--descent",
    String(descent),
    "--line-height",
    String(lineHeight),
    "--letter-spacing",
    String(letterSpacing),
  ];

  if (monospace) {
    args.push("--monospace");
  }

  return runProcess(FONTFORGE_BIN, args);
}
