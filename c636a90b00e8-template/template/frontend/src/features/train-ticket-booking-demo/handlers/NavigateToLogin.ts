export type NavigateToLoginInput = {  };
export type NavigateToLoginOutput = {  };

export async function NavigateToLogin(_input: NavigateToLoginInput): Promise<NavigateToLoginOutput> {
  window.location.assign("/login");
  return {};
}
