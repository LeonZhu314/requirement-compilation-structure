export type ChangeUsernameInput = { "value": string; };
export type ChangeUsernameOutput = {  };

/**
 * The entered username is held in the registration page state; uniqueness is
 * only checked when the form is submitted.
 */
export async function ChangeUsername(_input: ChangeUsernameInput): Promise<ChangeUsernameOutput> {
  return {};
}
