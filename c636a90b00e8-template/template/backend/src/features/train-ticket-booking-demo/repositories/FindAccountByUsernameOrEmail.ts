import { getDatabase } from "../../../db/client.js";

export type FindAccountByUsernameOrEmailInput = { "username": string; "email": string; };
export type FindAccountByUsernameOrEmailOutput = { "username_taken": boolean; "email_taken": boolean; };

export async function FindAccountByUsernameOrEmail(input: FindAccountByUsernameOrEmailInput): Promise<FindAccountByUsernameOrEmailOutput> {
  const database = getDatabase();
  const usernameMatch = database
    .prepare('SELECT 1 AS "present" FROM "user_account" WHERE "username" = ? LIMIT 1')
    .get(input.username) as { present: number } | undefined;
  const emailMatch = database
    .prepare('SELECT 1 AS "present" FROM "user_account" WHERE "email" = ? COLLATE NOCASE LIMIT 1')
    .get(input.email) as { present: number } | undefined;

  return { username_taken: Boolean(usernameMatch), email_taken: Boolean(emailMatch) };
}
