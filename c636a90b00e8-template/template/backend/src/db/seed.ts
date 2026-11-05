// Shared startup fixture module. Add cumulative requirement fixtures in the transaction below.
import type Database from "better-sqlite3";
import { initializeDatabase } from "./initialize.js";

/** Reset only this connection's database, then create schema and insert all accumulated fixtures. */
export function seedDatabase(connection: Database.Database): void {
  connection.pragma("foreign_keys = OFF");
  try {
    connection.transaction(() => {
      const tables = connection.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").all() as Array<{ name: string }>;
      for (const { name } of tables) connection.exec('DROP TABLE IF EXISTS "' + name.replaceAll('"', '""') + '"');
    })();
  } finally {
    connection.pragma("foreign_keys = ON");
  }
  initializeDatabase(connection);
  connection.transaction(() => {
    // Add INSERT statements here. Preserve fixtures accumulated for earlier requirements.
    // Use the application's actual password/hash encoding; do not create a logged-in session
    // unless the requirement explicitly states one already exists.
  })();
}
