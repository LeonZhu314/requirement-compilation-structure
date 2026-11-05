import { CreateTravelerAccount } from "../services/CreateTravelerAccount.js";
export async function RegisterAccount(input) {
    const result = await CreateTravelerAccount(input);
    if (result.error || !result.username || !result.session_id) {
        return { error: result.error ?? "Registration failed." };
    }
    return { username: result.username, session_id: result.session_id };
}
