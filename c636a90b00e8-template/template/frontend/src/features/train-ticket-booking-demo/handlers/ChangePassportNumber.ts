export type ChangePassportNumberInput = { "value": string; };
export type ChangePassportNumberOutput = {  };

/**
 * The entered passport number is held in the registration page state; no API
 * call is made while typing and validation happens on submission.
 */
export async function ChangePassportNumber(_input: ChangePassportNumberInput): Promise<ChangePassportNumberOutput> {
  return {};
}
