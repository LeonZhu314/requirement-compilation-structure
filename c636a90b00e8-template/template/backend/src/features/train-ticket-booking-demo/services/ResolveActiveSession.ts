import { FindSessionAccountById } from "../repositories/FindSessionAccountById.js";

export type ResolveActiveSessionInput = { "session_id"?: (string | null); };
export type ResolveActiveSessionOutput = { "authenticated": boolean; "username": (string | null); };

export async function ResolveActiveSession(input: ResolveActiveSessionInput): Promise<ResolveActiveSessionOutput> {
  if (!input.session_id) return { authenticated: false, username: null };

  const session = await FindSessionAccountById({ session_id: input.session_id });
  if (!session.found) return { authenticated: false, username: null };

  return { authenticated: true, username: session.username };
}
