/**
 * Express server setup — entry point for the TypeScript font generation orchestrator
 */

import express from "express";
import cors from "cors";
import { PORT, CORS_ORIGINS } from "./constants.js";
import { failOrphanedJobs } from "./jobStore.js";
import generateFontRouter from "./routes/generateFont.js";
import jobStatusRouter from "./routes/jobStatus.js";
import jobResultRouter from "./routes/jobResult.js";
import staticIndexRouter from "./routes/staticIndex.js";

const app = express();

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// CORS: custom middleware to support Private Network Access header
app.use(
  cors({
    origin: CORS_ORIGINS,
    credentials: true,
  })
);

// Add Access-Control-Allow-Private-Network header (Chrome PNA requirement)
app.use((_req, res, next) => {
  res.header("Access-Control-Allow-Private-Network", "true");
  next();
});

// Initialize job store (fail orphaned jobs at startup)
failOrphanedJobs();

// Routes
app.use(generateFontRouter);
app.use(jobStatusRouter);
app.use(jobResultRouter);
app.use(staticIndexRouter);

// Health check
app.get("/health", (_req, res) => {
  res.status(200).json({ status: "ok" });
});

// Graceful shutdown
let server: any;
const shutdown = () => {
  console.log("\nShutting down gracefully...");
  if (server) {
    server.close(() => {
      console.log("Server closed");
      process.exit(0);
    });
  }
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

// Start server
server = app.listen(PORT, () => {
  console.log(`🚀 png2font API server running at http://127.0.0.1:${PORT}`);
  console.log(`   POST   /api/generate-font       — submit font generation job`);
  console.log(`   GET    /api/job/:id             — get job status`);
  console.log(`   GET    /api/job/:id/result      — download result ZIP`);
  console.log(`   GET    /health                  — health check`);
});

export default app;
