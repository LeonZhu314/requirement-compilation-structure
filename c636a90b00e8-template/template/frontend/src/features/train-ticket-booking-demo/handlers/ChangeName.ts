export type ChangeNameInput = { "value": string; };
export type ChangeNameOutput = {  };

/**
 * The entered name is held in the registration page state; no API call is made
 * while typing and validation happens on submission.
 */
export async function ChangeName(_input: ChangeNameInput): Promise<ChangeNameOutput> {
  return {};
}
