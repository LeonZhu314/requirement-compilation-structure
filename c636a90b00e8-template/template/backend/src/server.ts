import { createApp } from "./app.js";
import { serverPort } from "./config/server.js";
import { createDatabaseClient, bindDatabaseClient } from "./db/client.js";
import { seedDatabase } from "./db/seed.js";
import { initializeDatabase } from "./db/initialize.js";
const client = createDatabaseClient();
try { if (process.env.ARC_VALIDATION_PREPARED === "1") initializeDatabase(client.connection);
else seedDatabase(client.connection); bindDatabaseClient(client); }
catch (error) { client.close(); throw error; }
const port = serverPort();
export const server = createApp().listen(port, () => {
  const address = server.address();
  const actualPort = address && typeof address === "object" ? address.port : port;
  console.log(`Application ready: http://localhost:${actualPort}`);
  console.log(`Health: http://localhost:${actualPort}/__arc/health`);
});
server.on("error", (error: NodeJS.ErrnoException) => {
  console.error(error.code === "EADDRINUSE" ? `Port ${port} is already in use` : error.message);
  client.close(); process.exitCode = 1;
});
server.on("close", () => client.close());
process.once("SIGTERM", () => server.close());
process.once("SIGINT", () => server.close());
