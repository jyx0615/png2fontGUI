/**
 * GET / fallback handler + /static mount
 */

import { Router, Response } from "express";
import { existsSync, readFileSync } from "fs";
import express from "express";

const router = Router();

const fallbackHTML = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>png2font API Server</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #0f0c20 0%, #15102a 100%);
            color: #fff;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            height: 100vh;
            text-align: center;
        }
        .card {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 20px;
            padding: 40px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(90deg, #a855f7 0%, #3b82f6 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        p {
            color: #94a3b8;
            margin-bottom: 30px;
        }
        a {
            display: inline-block;
            background: linear-gradient(90deg, #a855f7 0%, #6366f1 100%);
            color: #fff;
            text-decoration: none;
            padding: 12px 30px;
            border-radius: 30px;
            font-weight: 600;
            transition: transform 0.2s, box-shadow 0.2s;
            box-shadow: 0 4px 15px rgba(168, 85, 247, 0.4);
        }
        a:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(168, 85, 247, 0.6);
        }
    </style>
</head>
<body>
    <div class="card">
        <h1>png2font API Server</h1>
        <p>The font generation backend is fully active and operational.</p>
        <a href="/static">Explore Web UI</a>
    </div>
</body>
</html>
`;

router.get("/", (_req, res: Response) => {
  const indexPath = "static/index.html";
  if (existsSync(indexPath)) {
    const content = readFileSync(indexPath, "utf-8");
    return res.type("text/html").send(content);
  }
  return res.type("text/html").send(fallbackHTML);
});

// Mount static directory if it exists
if (existsSync("static")) {
  router.use("/static", express.static("static"));
}

export default router;
