/**
 * Shared subprocess runner — spawn process, capture stdout/stderr, return exit code.
 * Mirrors Python's subprocess.run(check=False): never auto-throws on nonzero exit,
 * leaves error handling to the caller.
 */

import { spawn } from "child_process";
import { RunProcessResult } from "../types.js";

export interface RunProcessOptions {
  cwd?: string;
  env?: NodeJS.ProcessEnv;
}

/**
 * Spawns a process and captures its output.
 * Always returns normally (never throws on nonzero exit).
 * The caller decides what to do based on the exit code.
 */
export async function runProcess(
  command: string,
  args: string[],
  options?: RunProcessOptions
): Promise<RunProcessResult> {
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";

    const child = spawn(command, args, {
      cwd: options?.cwd,
      env: options?.env ?? process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    if (child.stdout) {
      child.stdout.on("data", (data) => {
        stdout += data.toString();
      });
    }

    if (child.stderr) {
      child.stderr.on("data", (data) => {
        stderr += data.toString();
      });
    }

    child.on("close", (code) => {
      resolve({
        code: code ?? null,
        stdout,
        stderr,
      });
    });

    child.on("error", (err) => {
      resolve({
        code: 1,
        stdout,
        stderr: stderr + `\nFailed to spawn process: ${err.message}`,
      });
    });
  });
}

/**
 * Variant that streams stdout line-by-line to a callback.
 * Used for long-running processes like nanoemoji's maximum_color.
 */
export async function runProcessStreaming(
  command: string,
  args: string[],
  onLine: (line: string) => void,
  options?: RunProcessOptions
): Promise<RunProcessResult> {
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    let partialLine = "";

    const child = spawn(command, args, {
      cwd: options?.cwd,
      env: options?.env ?? process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    if (child.stdout) {
      child.stdout.on("data", (data) => {
        const text = data.toString();
        stdout += text;
        partialLine += text;

        const lines = partialLine.split("\n");
        for (let i = 0; i < lines.length - 1; i++) {
          onLine(lines[i]);
        }
        partialLine = lines[lines.length - 1];
      });
    }

    if (child.stderr) {
      child.stderr.on("data", (data) => {
        stderr += data.toString();
      });
    }

    child.on("close", (code) => {
      if (partialLine) {
        onLine(partialLine);
      }
      resolve({
        code: code ?? null,
        stdout,
        stderr,
      });
    });

    child.on("error", (err) => {
      resolve({
        code: 1,
        stdout,
        stderr: stderr + `\nFailed to spawn process: ${err.message}`,
      });
    });
  });
}
