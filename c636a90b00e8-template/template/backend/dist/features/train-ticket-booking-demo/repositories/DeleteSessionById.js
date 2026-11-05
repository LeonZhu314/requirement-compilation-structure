import { getDatabase } from "../../../db/client.js";
export async function DeleteSessionById(input) {
    getDatabase().prepare('DELETE FROM "session" WHERE "id" = ?').run(input.session_id);
    return {};
}
