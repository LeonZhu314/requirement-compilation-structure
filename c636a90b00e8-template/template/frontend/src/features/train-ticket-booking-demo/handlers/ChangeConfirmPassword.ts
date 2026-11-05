export type ChangeConfirmPasswordInput = { "value": string; };
export type ChangeConfirmPasswordOutput = {  };

/**
 * The entered hidden confirmation text is held in the registration page state;
 * the match with the password is evaluated on submission.
 */
export async function ChangeConfirmPassword(_input: ChangeConfirmPasswordInput): Promise<ChangeConfirmPasswordOutput> {
  return {};
}
