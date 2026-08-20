/**
 * Configuration loading and utilities — ported from Python config.py
 */

import { readFileSync } from "fs";
import { parse } from "smol-toml";
import { FontConfig, VerticalMetricsResult } from "./types.js";

/**
 * Computes vertical metrics (ascent, descent, line height) for a given UPM.
 * Uses the classic 80/20 em split with 1.2× line-height convention,
 * matching Times/Arial-class fonts so generated fonts drop in next to system fonts
 * without changing line spacing.
 */
export function verticalMetrics(upm: number): VerticalMetricsResult {
  const ascent = Math.round(upm * 0.8);
  const descent = upm - ascent;
  const lineHeight = Math.round(upm * 1.2);
  return { ascent, descent, lineHeight };
}

/**
 * Loads font configuration from config.toml, falling back to defaults.
 * Returns a FontConfig object with all required fields.
 */
export function loadFontConfig(configPath = "config.toml"): FontConfig {
  try {
    const content = readFileSync(configPath, "utf-8");
    const data = parse(content) as Record<string, unknown>;
    const fontSettings = (data.font as Record<string, unknown>) || {};

    return {
      upm: Number(fontSettings.upm ?? 1000),
      advanceWidth: Number(fontSettings.advance_width ?? 600),
      spaceWidth: Number(fontSettings.space_width ?? 250),
      fontname: String(fontSettings.fontname ?? "MyCustomFont"),
      fullname: String(fontSettings.fullname ?? "My Custom Font"),
      familyname: String(fontSettings.familyname ?? "My Family"),
    };
  } catch {
    // Config file missing or unparseable — use defaults
    return {
      upm: 1000,
      advanceWidth: 600,
      spaceWidth: 250,
      fontname: "MyCustomFont",
      fullname: "My Custom Font",
      familyname: "My Family",
    };
  }
}
