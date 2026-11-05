export type ChangeNationalityInput = { "value": string; };
export type ChangeNationalityOutput = {  };

/**
 * The selected nationality is held in the registration page state; the combobox
 * change itself never calls an API and performs no validation.
 */
export async function ChangeNationality(_input: ChangeNationalityInput): Promise<ChangeNationalityOutput> {
  return {};
}
