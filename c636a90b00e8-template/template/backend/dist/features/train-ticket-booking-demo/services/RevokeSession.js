import { DeleteSessionById } from "../repositories/DeleteSessionById.js";
export async function RevokeSession(input) {
    if (input.session_id) {
        await DeleteSessionById({ session_id: input.session_id });
    }
    return {};
}
