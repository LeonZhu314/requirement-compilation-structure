import type Database from "better-sqlite3";
import { getDatabase } from "../../../db/client.js";

export type InsertSessionInput = { "session_id": string; "account_id": string; };
export type InsertSessionOutput = { "session_id": string; };

const insertSessionSql = 'INSERT INTO "session" ("id", "user_account_id") VALUES (?, ?)';

/** Synchronous insert used inside the caller's transaction so account and session stay atomic. */
export function insertSessionRow(database: Database.Database, input: InsertSessionInput): void {
  database.prepare(insertSessionSql).run(input.session_id, input.account_id);
}

export async function InsertSession(input: InsertSessionInput): Promise<InsertSessionOutput> {
  insertSessionRow(getDatabase(), input);
  return { session_id: input.session_id };
}
