import { RevokeSession } from "../services/RevokeSession.js";
export async function SignOut(input) {
    await RevokeSession({ session_id: input.session_id ?? null });
    return {};
}
