export type SignOutAccountInput = {  };
export type SignOutAccountOutput = { success: boolean };

export async function SignOutAccount(_input: SignOutAccountInput): Promise<SignOutAccountOutput> {
  try {
    const response = await fetch("/api/session", {
      method: "DELETE",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    return { success: response.ok };
  } catch {
    return { success: false };
  }
}
