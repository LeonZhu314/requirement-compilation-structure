export type ChangeGenderInput = { "value": string; };
export type ChangeGenderOutput = {  };

/**
 * The selected gender radio option is held in the registration page state; no
 * API call is made when the selection changes.
 */
export async function ChangeGender(_input: ChangeGenderInput): Promise<ChangeGenderOutput> {
  return {};
}
