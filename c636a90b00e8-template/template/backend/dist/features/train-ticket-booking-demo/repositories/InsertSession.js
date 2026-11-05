import { getDatabase } from "../../../db/client.js";
const insertSessionSql = 'INSERT INTO "session" ("id", "user_account_id") VALUES (?, ?)';
/** Synchronous insert used inside the caller's transaction so account and session stay atomic. */
export function insertSessionRow(database, input) {
    database.prepare(insertSessionSql).run(input.session_id, input.account_id);
}
export async function InsertSession(input) {
    insertSessionRow(getDatabase(), input);
    return { session_id: input.session_id };
}
