export type LoadSessionStateInput = {  };
export type SessionState = { authenticated: boolean; username: string | null };
export type LoadSessionStateOutput = { session_state: SessionState };

export async function LoadSessionState(_input: LoadSessionStateInput): Promise<LoadSessionStateOutput> {
  try {
    const response = await fetch("/api/session", {
      method: "GET",
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Request failed with ${response.status}`);
    }
    const data = (await response.json()) as { authenticated?: unknown; username?: unknown };
    return {
      session_state: {
        authenticated: Boolean(data.authenticated),
        username: typeof data.username === "string" ? data.username : null,
      },
    };
  } catch {
    return { session_state: { authenticated: false, username: null } };
  }
}
