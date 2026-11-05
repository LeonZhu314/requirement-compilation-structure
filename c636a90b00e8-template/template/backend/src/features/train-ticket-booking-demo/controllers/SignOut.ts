import { RevokeSession } from "../services/RevokeSession.js";

export type SignOutInput = { "session_id"?: string; };
export type SignOutOutput = {  };

export async function SignOut(input: SignOutInput): Promise<SignOutOutput> {
  await RevokeSession({ session_id: input.session_id ?? null });
  return {};
}
