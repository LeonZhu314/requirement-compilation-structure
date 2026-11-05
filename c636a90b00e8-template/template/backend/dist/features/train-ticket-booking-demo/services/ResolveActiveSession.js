import { FindSessionAccountById } from "../repositories/FindSessionAccountById.js";
export async function ResolveActiveSession(input) {
    if (!input.session_id)
        return { authenticated: false, username: null };
    const session = await FindSessionAccountById({ session_id: input.session_id });
    if (!session.found)
        return { authenticated: false, username: null };
    return { authenticated: true, username: session.username };
}
