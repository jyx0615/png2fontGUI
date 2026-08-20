/**
 * nanoemoji maximum_color CLI wrapper — generates COLR v1 color table.
 * Streams output line-by-line for job status updates (nanoemoji can run 20+ min).
 */

import { createWriteStream } from "fs";
import { join } from "path";
import { runProcessStreaming } from "./runProcess.js";
import { MAXIMUM_COLOR_BIN, PYTHON_BIN } from "./toolPaths.js";
import { writeJobStatus } from "../jobStore.js";

export async function runMaximumColor(
  ttfPath: string,
  tempDir: string,
  jobId: string
): Promise<{ success: boolean; outputPath: string; stderr: string }> {
  const logPath = join(tempDir, "nanoemoji.log");
  const logStream = createWriteStream(logPath);

  let lastStatusWrite = 0;
  const lines: string[] = [];

  const result = await runProcessStreaming(
    MAXIMUM_COLOR_BIN,
    [ttfPath],
    (line) => {
      if (line.trim()) {
        lines.push(line);
        logStream.write(line + "\n");

        // Throttle job status updates to every 2s
        const now = Date.now();
        if (now - lastStatusWrite > 2000) {
          writeJobStatus(jobId, {
            detail: `nanoemoji: ${line.substring(0, 200)}`,
          });
          lastStatusWrite = now;
        }
      }
    },
    { cwd: tempDir }
  );

  logStream.end();

  const outputPath = join(tempDir, "build", "Font.ttf");

  if (result.code === 0) {
    return {
      success: true,
      outputPath,
      stderr: result.stderr,
    };
  }

  // Fallback: non-fatal on failure
  const lastLine = lines[lines.length - 1] ?? "";
  return {
    success: false,
    outputPath: "", // Will be handled by caller (copy non-color TTF)
    stderr: `maximum_color failed (exit ${result.code}); last output: ${lastLine}`,
  };
}
