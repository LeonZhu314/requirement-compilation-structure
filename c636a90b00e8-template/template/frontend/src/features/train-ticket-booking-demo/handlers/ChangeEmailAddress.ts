export type ChangeEmailAddressInput = { "value": string; };
export type ChangeEmailAddressOutput = {  };

/**
 * The entered email address is held in the registration page state; format and
 * uniqueness are only checked when the form is submitted.
 */
export async function ChangeEmailAddress(_input: ChangeEmailAddressInput): Promise<ChangeEmailAddressOutput> {
  return {};
}
