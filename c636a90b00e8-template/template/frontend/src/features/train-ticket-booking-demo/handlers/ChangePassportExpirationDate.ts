export type ChangePassportExpirationDateInput = { "value": string; };
export type ChangePassportExpirationDateOutput = {  };

/**
 * The entered passport expiration date is held in the registration page state;
 * no API call is made while entering the date.
 */
export async function ChangePassportExpirationDate(_input: ChangePassportExpirationDateInput): Promise<ChangePassportExpirationDateOutput> {
  return {};
}
