export type NavigateToRegisterInput = {  };
export type NavigateToRegisterOutput = {  };

export async function NavigateToRegister(_input: NavigateToRegisterInput): Promise<NavigateToRegisterOutput> {
  window.location.assign("/register");
  return {};
}
