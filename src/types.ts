/**
 * Type definitions for the png2font font generation service.
 */

export type JobLifecycleStatus = "queued" | "processing" | "completed" | "failed";

export interface JobStatus {
  status: JobLifecycleStatus;
  phase: string;
  detail: string;
  updated_at: number;
  zip_filename?: string;
}

export interface FontConfig {
  upm: number;
  advanceWidth: number;
  spaceWidth: number;
  fontname: string;
  fullname: string;
  familyname: string;
}

export interface GenerateFontParams {
  fontname: string;
  fullname: string;
  familyname: string;
  upm: number;
  advanceWidth: number;
  verticalRaise: number;
  monospace: boolean;
  lineHeight: number | null;
  letterSpacing: number;
}

export interface RunProcessResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

export interface VerticalMetricsResult {
  ascent: number;
  descent: number;
  lineHeight: number;
}
