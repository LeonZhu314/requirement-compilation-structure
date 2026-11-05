export type ChangeDateOfBirthInput = { "value": string; };
export type ChangeDateOfBirthOutput = {  };

/**
 * The entered date of birth is held in the registration page state; no API
 * call is made while entering or picking the date.
 */
export async function ChangeDateOfBirth(_input: ChangeDateOfBirthInput): Promise<ChangeDateOfBirthOutput> {
  return {};
}
