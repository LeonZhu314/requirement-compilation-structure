export type NavigateToHomeInput = {  };
export type NavigateToHomeOutput = {  };

export async function NavigateToHome(_input: NavigateToHomeInput): Promise<NavigateToHomeOutput> {
  window.location.assign("/");
  return {};
}
