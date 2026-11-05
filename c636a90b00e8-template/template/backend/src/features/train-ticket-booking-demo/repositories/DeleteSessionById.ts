import { getDatabase } from "../../../db/client.js";

export type DeleteSessionByIdInput = { "session_id": string; };
export type DeleteSessionByIdOutput = {  };

export async function DeleteSessionById(input: DeleteSessionByIdInput): Promise<DeleteSessionByIdOutput> {
  getDatabase().prepare('DELETE FROM "session" WHERE "id" = ?').run(input.session_id);
  return {};
}
