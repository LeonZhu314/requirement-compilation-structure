export type RegistrationPayload = {
  nationality: string;
  name: string;
  passport_number: string;
  passport_expiration_date: string;
  date_of_birth: string;
  gender: string;
  username: string;
  password: string;
  confirm_password: string;
  email: string;
  agreed_to_terms: boolean;
};

export type SubmitRegistrationInput = { payload?: RegistrationPayload };
export type SubmitRegistrationOutput = { username?: string; error?: string };

export async function SubmitRegistration(
  input: SubmitRegistrationInput,
): Promise<SubmitRegistrationOutput> {
  const payload: RegistrationPayload = input.payload ?? {
    nationality: "",
    name: "",
    passport_number: "",
    passport_expiration_date: "",
    date_of_birth: "",
    gender: "",
    username: "",
    password: "",
    confirm_password: "",
    email: "",
    agreed_to_terms: false,
  };

  try {
    const response = await fetch("/api/register", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = (await response.json().catch(() => ({}))) as {
      username?: unknown;
      error?: unknown;
    };

    if (typeof data.error === "string" && data.error.length > 0) {
      return { error: data.error };
    }

    if (response.ok && typeof data.username === "string" && data.username.length > 0) {
      return { username: data.username };
    }

    return { error: "Registration failed. Please check the information you entered." };
  } catch {
    return { error: "Registration failed. Please try again." };
  }
}
