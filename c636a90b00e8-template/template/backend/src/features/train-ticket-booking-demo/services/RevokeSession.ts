import { DeleteSessionById } from "../repositories/DeleteSessionById.js";

export type RevokeSessionInput = { "session_id"?: (string | null); };
export type RevokeSessionOutput = {  };

export async function RevokeSession(input: RevokeSessionInput): Promise<RevokeSessionOutput> {
  if (input.session_id) {
    await DeleteSessionById({ session_id: input.session_id });
  }
  return {};
}
