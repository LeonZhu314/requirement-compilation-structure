import { CreateTravelerAccount } from "../services/CreateTravelerAccount.js";

export type RegisterAccountInput = { "nationality": string; "name": string; "passport_number": string; "passport_expiration_date": string; "date_of_birth": string; "gender": ("Male" | "Female"); "username": string; "password": string; "confirm_password": string; "email": string; "agreed_to_terms": boolean; };
export type RegisterAccountOutput = { "username"?: string; "session_id"?: string; "error"?: string; };

export async function RegisterAccount(input: RegisterAccountInput): Promise<RegisterAccountOutput> {
  const result = await CreateTravelerAccount(input);
  if (result.error || !result.username || !result.session_id) {
    return { error: result.error ?? "Registration failed." };
  }
  return { username: result.username, session_id: result.session_id };
}
