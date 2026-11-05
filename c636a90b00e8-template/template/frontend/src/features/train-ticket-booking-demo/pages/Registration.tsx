import { useState } from "react";
import { RegistrationHeader } from "../components/RegistrationHeader";
import { RegistrationPrimaryNavigation } from "../components/RegistrationPrimaryNavigation";
import { BreadcrumbRegion } from "../components/BreadcrumbRegion";
import { RegistrationCard } from "../components/RegistrationCard";
import { RegistrationFooter } from "../components/RegistrationFooter";
import { SubmitRegistration } from "../handlers/SubmitRegistration";
import type { RegistrationFormValues } from "../components/RegistrationForm";

export type RegistrationState = { "nationality": string; "name": string; "passport_number": string; "passport_expiration_date": string; "date_of_birth": string; "gender": string; "username": string; "password": string; "confirm_password": string; "email": string; "agreed_to_terms": boolean; "registration_error_message": (string | null); "registration_submitting": boolean; };
export type RegistrationProps = {};

const initialValues: RegistrationFormValues = {
  nationality: "",
  name: "",
  passport_number: "",
  passport_expiration_date: "",
  date_of_birth: "",
  gender: "",
  username: "",
  password: "",
  confirm_password: "",
  email: "",
  agreed_to_terms: false,
};

export function Registration(_props: RegistrationProps) {
  const [values, setValues] = useState<RegistrationFormValues>(initialValues);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleChange = (field: keyof RegistrationFormValues, value: string | boolean) => {
    setValues((current) => ({ ...current, [field]: value }) as RegistrationFormValues);
  };

  const handleSubmit = async () => {
    if (submitting) {
      return;
    }
    setErrorMessage(null);
    setSubmitting(true);
    const result = await SubmitRegistration({ payload: values });
    setSubmitting(false);
    if (result.username) {
      window.location.assign("/");
      return;
    }
    setErrorMessage(result.error ?? "Registration failed. Please check the information you entered.");
  };

  return (
    <section data-ui-id="UI_000047" className="flex min-h-screen flex-col bg-white">
      <RegistrationHeader />
      <RegistrationPrimaryNavigation />
      <main className="flex-1">
        <BreadcrumbRegion />
        <RegistrationCard
          values={values}
          errorMessage={errorMessage}
          submitting={submitting}
          onChange={handleChange}
          onSubmit={handleSubmit}
        />
      </main>
      <RegistrationFooter />
    </section>
  );
}
