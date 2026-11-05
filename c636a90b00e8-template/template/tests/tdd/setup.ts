import { afterAll } from "vitest";
import { createDatabaseClient, bindDatabaseClient } from "../../backend/src/db/client.js";
import { seedDatabase } from "../../backend/src/db/seed.js";
const client = createDatabaseClient(process.env.DATABASE_URL ?? ":memory:");
seedDatabase(client.connection);
bindDatabaseClient(client);
afterAll(() => client.close());
