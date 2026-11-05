export type ChangeTermsAgreementInput = { "value": boolean; };
export type ChangeTermsAgreementOutput = {  };

/**
 * The checked state of the agreement checkbox is held in the registration page
 * state; no API call is made when it is toggled.
 */
export async function ChangeTermsAgreement(_input: ChangeTermsAgreementInput): Promise<ChangeTermsAgreementOutput> {
  return {};
}
