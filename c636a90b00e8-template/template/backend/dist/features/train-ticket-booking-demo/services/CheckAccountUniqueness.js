import { FindAccountByUsernameOrEmail } from "../repositories/FindAccountByUsernameOrEmail.js";
export async function CheckAccountUniqueness(input) {
    return FindAccountByUsernameOrEmail({ username: input.username, email: input.email });
}
