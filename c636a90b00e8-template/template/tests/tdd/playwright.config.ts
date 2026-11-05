import { defineConfig } from "@playwright/test";
const port = process.env.ARC_TDD_PORT ?? "33100";
export default defineConfig({
  testDir: "../e2e", workers: 1, fullyParallel: false, retries: 0,
  outputDir: process.env.ARC_TDD_RESULTS_DIR ?? "../test-results",
  timeout: 30000, use: { baseURL: "http://127.0.0.1:" + port },
  webServer: process.env.ARC_TDD_EXTERNAL_SERVER === "1" ? undefined : { command: "node backend/dist/server.js", cwd: "../..",
    url: "http://127.0.0.1:" + port + "/__arc/health", reuseExistingServer: false,
    env: { PORT: port, NODE_ENV: "test", DATABASE_URL: process.env.DATABASE_URL ?? ":memory:" },
    timeout: 30000,
  },
});
