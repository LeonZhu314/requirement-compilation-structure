import type Database from "better-sqlite3";
import { getDatabase } from "../../../db/client.js";

export type InsertUserAccountInput = { "account_id": string; "nationality": string; "name": string; "passport_number": string; "passport_expiration_date": string; "date_of_birth": string; "gender": ("Male" | "Female"); "username": string; "email": string; "password_hash": string; };
export type InsertUserAccountOutput = { "account_id": string; };

const insertUserAccountSql =
  'INSERT INTO "user_account" ("id", "nationality", "name", "passport_number", "passport_expiration_date", "date_of_birth", "gender", "username", "email", "password") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)';

/** Synchronous insert used inside the caller's transaction so account and session stay atomic. */
export function insertUserAccountRow(database: Database.Database, input: InsertUserAccountInput): void {
  database
    .prepare(insertUserAccountSql)
    .run(
      input.account_id,
      input.nationality,
      input.name,
      input.passport_number,
      input.passport_expiration_date,
      input.date_of_birth,
      input.gender,
      input.username,
      input.email,
      input.password_hash
    );
}

export async function InsertUserAccount(input: InsertUserAccountInput): Promise<InsertUserAccountOutput> {
  insertUserAccountRow(getDatabase(), input);
  return { account_id: input.account_id };
}
