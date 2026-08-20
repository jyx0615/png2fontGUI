# png2font_api — TypeScript/Node Hybrid Font Generation Service

## Project Overview

A web service that converts PNG glyph images into TTF/WOFF2 fonts. The service uses a **hybrid architecture**: TypeScript/Node orchestrates the HTTP API, job management, and status tracking, while delegating font engineering to proven external tools (FontForge, nanoemoji, fontTools) as subprocesses.

**Why hybrid?** Three core font tools have no JavaScript equivalent and would be weeks to rewrite from scratch:
- **FontForge** — SVG→TTF outline compilation + boolean overlap union
- **nanoemoji** — COLR v1 color-font table compiler  
- **fontTools** — TTF binary table surgery (sbix grafting, table deletion)

By calling them as subprocesses, we keep the reliability of battle-tested tools while gaining the simplicity of Node.js for orchestration.

## Architecture at a Glance

```
Client HTTP
    ↓
Express Server (src/server.ts, port 8000)
    ├→ POST /api/generate-font ──→ Save PNGs, kick off job (fire-and-forget)
    ├→ GET /api/job/:id ──→ Poll status (phase, progress, updated_at)
    └→ GET /api/job/:id/result ──→ Download ZIP when status="completed"
    
Fire-and-forget Pipeline (src/pipeline.ts)
    ├→ 11-phase state machine: queued → tracing → fontforge → color-optimize → woff → zipping → done
    ├→ Heartbeat (every 15s) — updates "last seen" timestamp
    ├→ Spawns subprocesses synchronously (await each step)
    └→ Atomic status writes to job directory (tempdir/png2font_jobs/{jobId}/status.json)

Job Store (src/jobStore.ts)
    ├→ Disk-backed: one status.json per job directory
    ├→ Per-job async locks: prevent heartbeat + main pipeline from interleaving writes
    ├→ Sync fs.writeFileSync + atomic rename: mirrors Python's threading.Lock
    └→ TTL sweep: deletes job dirs > 2 hours old on every POST start

Subprocess Wrappers (src/subprocess/)
    ├→ fontforge.ts → fontforge -script font.py ...
    ├→ addsvg.ts → addsvg <svgFolder> <ttfPath>
    ├→ maximumColor.ts → nanoemoji maximum_color (streamed stdout for progress)
    ├→ ttf2woff2.ts → pipe TTF through stdin/stdout
    ├→ png2svgCli.ts → python3 png2svg.py {trace,shift,flatten}
    └→ fontTablesCli.ts → python3 font_tables.py {add-sbix,drop-tables}
```

## File Structure

### Core (TypeScript, compiled to `dist/`)
- **src/server.ts** — Express app, CORS, routes, listen() on port 8000
- **src/pipeline.ts** — Main orchestrator: runGenerationJob() phase machine + heartbeat
- **src/jobStore.ts** — jobDir(), writeJobStatus(), readJobStatus(), sweepStaleJobs(), failOrphanedJobs()
- **src/config.ts** — svgFilenameToCodepoint(), verticalMetrics(), loadFontConfig() — pure utilities ported from Python
- **src/types.ts** — JobStatus, JobLifecycleStatus, FontConfig, GenerateFontParams, RunProcessResult
- **src/constants.ts** — JOBS_ROOT, JOB_TTL_SECONDS, JOB_ID_RE, CORS_ORIGINS, PORT

### Routes (HTTP handlers)
- **src/routes/generateFont.ts** — POST /api/generate-font: upload PNGs, validate, create job, start pipeline
- **src/routes/jobStatus.ts** — GET /api/job/:id: return job status JSON
- **src/routes/jobResult.ts** — GET /api/job/:id/result: download ZIP when completed
- **src/routes/staticIndex.ts** — GET /: serve static/index.html or fallback HTML, mount /static

### Subprocess Wrappers
- **src/subprocess/runProcess.ts** — Shared spawn + capture-stdout/stderr + exit-code helper
- **src/subprocess/toolPaths.ts** — Binary path resolution: env-var → which → fallback
- **src/subprocess/fontforge.ts** — runFontForge(svgFolder, ..., monospace?)
- **src/subprocess/addsvg.ts** — runAddsvg(svgFolder, ttfPath)
- **src/subprocess/maximumColor.ts** — runMaximumColor(ttfPath, tempDir, jobId) with streaming progress
- **src/subprocess/ttf2woff2.ts** — runTtf2Woff2(ttfPath, woff2Path) via stdin/stdout pipe
- **src/subprocess/png2svgCli.ts** — runPng2SvgTrace/Shift/Flatten
- **src/subprocess/fontTablesCli.ts** — runAddSbixTable, runDropUnusedTables

### Config & Deployment
- **package.json** — Dependencies (express, multer, cors, archiver, smol-toml, which); scripts (build, start, dev)
- **tsconfig.json** — Strict mode, ES2020, ES modules, .js extensions
- **run.sh** — Activate conda, npm run build && npm start
- **setup_env.sh** — (unchanged) Provision FontForge, nanoemoji, ttf2woff2, Python packages

### Python Scripts (called as subprocesses from TypeScript)
- **png2svg.py** — Argparse subcommands: `trace`, `shift`, `flatten`
- **font_tables.py** — Argparse subcommands: `add-sbix`, `drop-tables`
- **font.py** — FontForge script (unchanged, invoked by fontforge.ts)
- **config.py** — Shared config utilities (unchanged, imported by Python scripts)

## Pipeline Execution Flow

When a user POSTs a font generation job:

1. **HTTP Handler** saves PNG files to `tempdir/png2font_jobs/{jobId}/png_glyphs/`, writes initial status
2. **runGenerationJob()** fires and forgets (async, no await):
   - Starts heartbeat: every 15s updates `updated_at` in status.json
   - Phase 1 (tracing): PNG → SVG via `python3 png2svg.py trace`
   - Phase 2 (shifting): SVG vertical metrics via `python3 png2svg.py shift`
   - Phase 3 (flattening): Union overlaps via `python3 png2svg.py flatten`
   - Phase 4 (fontforge): SVG → TTF via `fontforge -script font.py`
   - Phase 5 (svg-embed): Embed SVG outlines via `addsvg` (non-fatal if fails)
   - Phase 6 (color-optimize): COLR table via `nanoemoji maximum_color` (streams progress, falls back to non-color TTF)
   - Phase 7 (sbix): Add sbix table via `python3 font_tables.py add-sbix` (non-fatal)
   - Phase 8 (drop tables for TTF): Remove redundant tables via `python3 font_tables.py drop-tables` (non-fatal)
   - Phase 9 (woff): TTF → WOFF2 via `ttf2woff2` pipeline (non-fatal)
   - Phase 10 (drop tables for WOFF2): Optimize WOFF2 via `font_tables.py drop-tables` (non-fatal)
   - Phase 11 (zipping): Create ZIP (TTF + WOFF2 if present), mark status="completed"
3. **Heartbeat stops** when pipeline completes or fails
4. **Job polling** reads status.json; clients see phase, detail, updated_at
5. **Result download** checks status="completed", serves ZIP file

## Key Design Decisions

### 1. Atomic Status Writes
**Problem:** Heartbeat callback and main pipeline both write status.json; without synchronization, one could clobber the other.

**Solution:** Per-job async locks (Map<jobId, Promise>) + synchronous fs.writeFileSync + atomic rename:
```typescript
// Lock ensures serial writes; sync fs avoids JavaScript event loop interleaving
const lock = perJobLocks.get(jobId) ?? Promise.resolve();
perJobLocks.set(jobId, lock.then(async () => {
  // Read → merge → write → rename atomically
  const current = readJobStatus(jobId) ?? {};
  const merged = { ...current, ...fields, updated_at: now };
  fs.writeFileSync(tmpPath, JSON.stringify(merged));
  fs.renameSync(tmpPath, statusPath);  // atomic rename
}));
```

### 2. Fire-and-Forget Pipeline
**Why?** HTTP handler returns 202 immediately; long font generation doesn't block the server.

**How?** `void runGenerationJob(...)` — no await, no .catch(), exceptions caught internally.

**Cleanup:** Heartbeat detects jobs silent >90 seconds (likely crashed) and marks them failed.

### 3. Non-Fatal Tool Failures
**Design:** Some tools are best-effort (addsvg, nanoemoji, sbix grafting). Failures don't stop the pipeline; they log warnings and the pipeline continues:
```typescript
// addsvg fails → log warning, continue with TTF alone
const result = await runAddsvg(...);
if (result.code !== 0) {
  console.warn(`addsvg failed (non-fatal): ${result.stderr}`);
}

// nanoemoji fails → copy uncolored TTF, continue
const colorResult = await runMaximumColor(...);
if (!colorResult.success) {
  copyFileSync(outputTtf, outputTtfColor);  // fallback
}
```

### 4. Job Status Merge, Not Replace
**Problem:** Heartbeat updates only `updated_at`, but if we replace the entire status.json, we lose phase/detail from the main pipeline.

**Solution:** Read-modify-write merge:
```typescript
const current = readJobStatus(jobId);  // existing status
const merged = { ...current, ...newFields, updated_at: now };  // merge, then update timestamp
writeFileSync(..., JSON.stringify(merged));
```

### 5. Environment Variable Binary Resolution
**Why?** Different machines have FontForge, nanoemoji, etc. in different paths.

**How?** Chain resolution: env-var → `which` command → fallback path
```typescript
// FONTFORGE_BIN = process.env.FONTFORGE_BIN || "fontforge"
// Then spawn tries that command; if not in PATH, Unix/shell will error helpfully
```

### 6. Python CLI Subcommands (argparse)
**Why?** png2svg.py and font_tables.py contain functions (trace, shift, flatten, add_sbix, drop_tables) that the Python code calls directly, but TypeScript must invoke them as subprocess CLI commands.

**Solution:** Refactor to argparse subparsers:
```bash
python3 png2svg.py trace --png-folder ... --svg-output ... --target-upm ...
python3 png2svg.py shift --svg-folder ... --out-folder ... --target-upm ... --descent ...
python3 font_tables.py add-sbix --font-path ... --build-dir ... --source-ttf-path ...
```

## Development

### Build & Run

```bash
npm install                # Install dependencies
npm run build              # Compile src/ → dist/ (tsc)
npm start                  # Run dist/server.js (production)
npm run dev                # Watch mode (tsx watch src/server.ts)
```

### Testing a Font Generation Job

```bash
# 1. Create test PNGs (or use existing glyphs/)
# 2. Start server
npm start

# 3. Upload and start job
curl -F "files=@glyphs/A.png" \
     -F "fontname=TestFont" \
     -F "fullname=Test Font" \
     http://127.0.0.1:8000/api/generate-font

# Returns: { "job_id": "abcd1234...", "status": "queued" }

# 4. Poll status
curl http://127.0.0.1:8000/api/job/abcd1234

# 5. When status="completed", download result
curl http://127.0.0.1:8000/api/job/abcd1234/result -o fonts.zip
unzip fonts.zip
```

### TypeScript Strict Mode
All code runs with `"strict": true`. Key rules:
- No implicit `any`; all types explicit
- Import paths include `.js` extensions (ES module requirement)
- Async functions always return `Promise<T>`
- Error handling catches `unknown` and refines to `Error`

### Adding a New Subprocess Wrapper

1. Create `src/subprocess/myTool.ts`
2. Import `runProcess` from `./runProcess.js`
3. Export async function that returns `RunProcessResult`
4. Resolve binary path in `toolPaths.ts` if needed
5. Import and call from `pipeline.ts`

Example:
```typescript
import { runProcess } from "./runProcess.js";

export async function runMyTool(input: string): Promise<RunProcessResult> {
  return runProcess("my-tool", ["--input", input]);
}
```

## Behavioral Fidelity

This codebase was ported from `app.py`, `pipeline.py`, `job_store.py` with exact parity. Key invariants:

- **Upload field name:** `"files"` (multipart/form-data, confirmed in frontend HTML)
- **Job ID format:** 32 lowercase hex chars (crypto.randomBytes(16).toString("hex"))
- **Status shape:** `{ status, phase, detail, updated_at (epoch seconds), zip_filename? }`
- **CORS allowlist:** 5 origins from app.py (localhost:3000, 127.0.0.1:3000, etc.)
- **Error response:** `{ detail: "..." }` (FastAPI-style)
- **Monospace coercion:** FormData sends `"true"`/`"false"` strings; coerce explicitly

## Troubleshooting

### Build Errors
- `Cannot find module 'X'`: Run `npm install`
- TS type errors: Check `.js` extensions in imports (ES modules require them)
- `tsc` fails: Ensure `tsconfig.json` has `"strict": true` and `"module": "ES2020"`

### Runtime Errors
- `fontforge not found`: Conda env not activated; run `source activate genFontAPI`
- `job not found (404)`: Job already deleted by TTL sweep (2-hour expiry)
- `Cannot write to tempdir`: Ensure `/tmp` (or $TMPDIR on macOS) has write permissions
- `nanoemoji fails`: Check if `nanoemoji` package installed in conda env (`pip list | grep nanoemoji`)

### Performance
- PNG tracing (vtracer) is slow; use parallel workers in `png2svg.py` (already implemented)
- Nanoemoji color optimization can take 10–20 minutes for large fonts
- WOFF2 conversion is fast (<1 second per font)

## Future Work

1. **Testing:** Add unit tests for jobStore, pipeline phases, subprocess error handling
2. **Logging:** Structured JSON logs with job_id, phase, duration
3. **Metrics:** Prometheus endpoints for job success rate, phase duration
4. **Scaling:** Job queue (Redis/Bull) to handle concurrent submissions
5. **CLI Tool:** Node.js CLI wrapper around the API for local batch generation
6. **Container:** Docker image bundling Node, Python, FontForge, nanoemoji
