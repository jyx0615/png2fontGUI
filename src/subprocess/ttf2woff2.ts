/**
 * ttf2woff2 CLI wrapper — converts TTF to WOFF2 via stdin/stdout pipe
 */

import { createReadStream, createWriteStream } from "fs";
import { spawn } from "child_process";
import { TTF2WOFF2_BIN } from "./toolPaths.js";
import { RunProcessResult } from "../types.js";

export async function runTtf2Woff2(ttfPath: string, woff2Path: string): Promise<RunProcessResult> {
  return new Promise((resolve) => {
    const input = createReadStream(ttfPath);
    const output = createWriteStream(woff2Path);
    let stderr = "";

    const child = spawn(TTF2WOFF2_BIN, [], {
      stdio: ["pipe", "pipe", "pipe"],
    });

    if (child.stderr) {
      child.stderr.on("data", (data) => {
        stderr += data.toString();
      });
    }

    input.pipe(child.stdin!);
    child.stdout!.pipe(output);

    child.on("close", (code) => {
      resolve({ code: code ?? null, stdout: "", stderr });
    });

    child.on("error", (err) => {
      resolve({ code: 1, stdout: "", stderr: `Failed to spawn ttf2woff2: ${err.message}` });
    });
  });
}
