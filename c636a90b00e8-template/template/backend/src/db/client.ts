import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { initializeDatabase } from "./initialize.js";

const defaultDatabase = fileURLToPath(new URL("../../data/app.db", import.meta.url));

export function createDatabaseClient(url = process.env.DATABASE_URL ?? defaultDatabase) {
  if (!url.trim()) throw new Error("DATABASE_URL must not be empty");
  if (url !== ":memory:") mkdirSync(dirname(resolve(url)), { recursive: true });
  const connection = new Database(url);
  connection.pragma("foreign_keys = ON");
  return { connection, close: () => connection.close() };
}

export type DatabaseClient = ReturnType<typeof createDatabaseClient>;

export let sqliteDatabase: Database.Database;
let schemaEnsured = false;

export function bindDatabaseClient(client: DatabaseClient): void {
  sqliteDatabase = client.connection;
  schemaEnsured = false;
}

/**
 * Returns the bound database connection. When no client has been bound yet (for
 * example in unit tests that exercise repositories/services directly), a private
 * in-memory database is created and initialized so the repository layer always has
 * the expected schema available.
 */
export function getDatabase(): Database.Database {
  if (!sqliteDatabase) {
    const client = createDatabaseClient(":memory:");
    initializeDatabase(client.connection);
    bindDatabaseClient(client);
  }
  if (!schemaEnsured) {
    initializeDatabase(sqliteDatabase);
    schemaEnsured = true;
  }
  return sqliteDatabase;
}

export function schemaTransaction<T>(work: () => T): T {
  return getDatabase().transaction(work)();
}
