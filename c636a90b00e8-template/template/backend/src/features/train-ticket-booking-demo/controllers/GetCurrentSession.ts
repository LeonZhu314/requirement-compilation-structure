import { ResolveActiveSession } from "../services/ResolveActiveSession.js";

export type GetCurrentSessionInput = { "session_id"?: string; };
export type GetCurrentSessionOutput = { "authenticated": boolean; "username": (string | null); };

export async function GetCurrentSession(input: GetCurrentSessionInput): Promise<GetCurrentSessionOutput> {
  return ResolveActiveSession({ session_id: input.session_id ?? null });
}
