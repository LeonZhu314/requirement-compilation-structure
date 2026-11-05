import { randomBytes, randomUUID, scryptSync } from "node:crypto";
import { getDatabase } from "../../../db/client.js";
import { insertSessionRow } from "../repositories/InsertSession.js";
import { insertUserAccountRow } from "../repositories/InsertUserAccount.js";
import { ValidateRegistration } from "./ValidateRegistration.js";

export type CreateTravelerAccountInput = { "nationality": string; "name": string; "passport_number": string; "passport_expiration_date": string; "date_of_birth": string; "gender": ("Male" | "Female"); "username": string; "password": string; "confirm_password": string; "email": string; "agreed_to_terms": boolean; };
export type CreateTravelerAccountOutput = { "username": (string | null); "session_id": (string | null); "error": (string | null); };

function hashPassword(plainPassword: string): string {
  const salt = randomBytes(16).toString("hex");
  const derived = scryptSync(plainPassword, salt, 64).toString("hex");
  return `scrypt$${salt}$${derived}`;
}

export async function CreateTravelerAccount(input: CreateTravelerAccountInput): Promise<CreateTravelerAccountOutput> {
  const validation = await ValidateRegistration(input);
  if (!validation.valid) {
    return { username: null, session_id: null, error: validation.error ?? "Registration failed." };
  }

  const accountId = randomUUID();
  const sessionId = randomUUID();
  const passwordHash = hashPassword(input.password);

  try {
    const database = getDatabase();
    database.transaction(() => {
      insertUserAccountRow(database, {
        account_id: accountId,
        nationality: input.nationality,
        name: input.name,
        passport_number: input.passport_number,
        passport_expiration_date: input.passport_expiration_date,
        date_of_birth: input.date_of_birth,
        gender: input.gender,
        username: input.username,
        email: input.email,
        password_hash: passwordHash,
      });
      insertSessionRow(database, { session_id: sessionId, account_id: accountId });
    })();
  } catch (error) {
    const message = error instanceof Error ? error.message : "Registration failed.";
    return { username: null, session_id: null, error: message };
  }

  return { username: input.username, session_id: sessionId, error: null };
}
