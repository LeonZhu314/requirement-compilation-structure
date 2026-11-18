import express from "express";
import type Database from "better-sqlite3";
import { registerApis } from "./api/register.js";
import { apiErrors } from "./lib/http.js";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function createApp(connection?: Database.Database) {
  const app = express();
  app.use(express.json());
  app.get("/api/health", (_request, response) => response.json({ status: "ok" }));
  if (connection) registerApis(app, connection);
  // Register business routes before this API fallback.
  app.use("/api", (_request, response) => response.status(404).json({ error: "Unknown API route" }));
  const frontend = fileURLToPath(new URL("../../frontend/dist/", import.meta.url));
  if (existsSync(frontend)) {
    app.use(express.static(frontend));
    // Any other GET is a client-side route: serve the page shell, so a reload or a direct visit
    // works. `root` matters: with an absolute path, a directory starting with a dot anywhere
    // above the application (".agent-state", "~/.cache") makes sendFile answer 404.
    app.get("/{*path}", (_request, response) => response.sendFile("index.html", { root: frontend }));
  }
  // Errors thrown by any route above become uniform JSON answers (lib/http.ts).
  app.use(apiErrors);
  return app;
}
