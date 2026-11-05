import { getDatabase } from "../../../db/client.js";
export async function FindSessionAccountById(input) {
    const row = getDatabase()
        .prepare('SELECT "user_account"."username" AS "username"\n' +
        'FROM "session"\n' +
        'INNER JOIN "user_account" ON "user_account"."id" = "session"."user_account_id"\n' +
        'WHERE "session"."id" = ?\n' +
        'LIMIT 1')
        .get(input.session_id);
    if (!row)
        return { found: false, username: null };
    return { found: true, username: row.username ?? null };
}
