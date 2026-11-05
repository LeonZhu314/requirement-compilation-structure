import { ResolveActiveSession } from "../services/ResolveActiveSession.js";
export async function GetCurrentSession(input) {
    return ResolveActiveSession({ session_id: input.session_id ?? null });
}
