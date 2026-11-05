import { getDatabase } from "../../../db/client.js";
export async function FindAccountByUsernameOrEmail(input) {
    const database = getDatabase();
    const usernameMatch = database
        .prepare('SELECT 1 AS "present" FROM "user_account" WHERE "username" = ? LIMIT 1')
        .get(input.username);
    const emailMatch = database
        .prepare('SELECT 1 AS "present" FROM "user_account" WHERE "email" = ? COLLATE NOCASE LIMIT 1')
        .get(input.email);
    return { username_taken: Boolean(usernameMatch), email_taken: Boolean(emailMatch) };
}
