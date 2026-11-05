import { FindAccountByUsernameOrEmail } from "../repositories/FindAccountByUsernameOrEmail.js";

export type CheckAccountUniquenessInput = { "username": string; "email": string; };
export type CheckAccountUniquenessOutput = { "username_taken": boolean; "email_taken": boolean; };

export async function CheckAccountUniqueness(input: CheckAccountUniquenessInput): Promise<CheckAccountUniquenessOutput> {
  return FindAccountByUsernameOrEmail({ username: input.username, email: input.email });
}
