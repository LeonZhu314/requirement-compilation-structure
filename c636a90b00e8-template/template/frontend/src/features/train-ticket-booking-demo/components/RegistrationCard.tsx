import { RegistrationForm, type RegistrationFormProps } from "./RegistrationForm";

export type RegistrationCardState = {  };
export type RegistrationCardProps = RegistrationFormProps;

export function RegistrationCard(props: RegistrationCardProps) {
  return (
    <section
      data-ui-id="UI_000064"
      className="mx-auto mt-4 w-full max-w-[1000px] border border-gray-200 bg-white px-5 py-9 shadow-[0_1px_3px_rgba(15,23,42,0.06)] sm:px-10"
    >
      <RegistrationForm {...props} />
    </section>
  );
}
