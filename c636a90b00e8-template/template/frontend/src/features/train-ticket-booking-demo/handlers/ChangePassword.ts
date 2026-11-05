export type ChangePasswordInput = { "value": string; };
export type ChangePasswordOutput = {  };

/**
 * The entered hidden password text is held in the registration page state; no
 * API call is made while typing.
 */
export async function ChangePassword(_input: ChangePasswordInput): Promise<ChangePasswordOutput> {
  return {};
}
