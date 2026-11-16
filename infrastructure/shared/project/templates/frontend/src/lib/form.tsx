import { useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

// Form controls whose accessible name is exactly their label, so users, screen
// readers and tests find "Username" as the textbox named "Username". Pass the
// label text exactly as the requirement writes it; put any "*" or hint elsewhere.
// Every component accepts className to restyle it; they carry no layout decisions.

const control = "block w-full rounded border border-gray-300 px-3 py-2";

type FieldProps = { label: string; error?: string; hint?: ReactNode };

function Described({ id, error, hint }: { id: string; error?: string; hint?: ReactNode }) {
  // No alert role here: a form has one alert (FormError); these are tied to their field.
  return (
    <>
      {hint ? <p id={`${id}-hint`} className="text-sm text-gray-500">{hint}</p> : null}
      {error ? <p id={`${id}-error`} className="text-sm text-red-600">{error}</p> : null}
    </>
  );
}

const describedBy = (id: string, error?: string, hint?: ReactNode) =>
  [error ? `${id}-error` : "", hint ? `${id}-hint` : ""].filter(Boolean).join(" ") || undefined;

/** Text, email, date or password input (set type); a password input is found by its label. */
export function TextField({ label, error, hint, className, ...input }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block font-medium">{label}</label>
      <input id={id} type="text" aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, error, hint)}
        className={className ?? control} {...input} />
      <Described id={id} error={error} hint={hint} />
    </div>
  );
}

export type Option = string | { value: string; label: string };
const optionValue = (option: Option) => (typeof option === "string" ? option : option.value);
const optionLabel = (option: Option) => (typeof option === "string" ? option : option.label);

/** Native <select>, exposed as the combobox named by its label. */
export function SelectField({ label, error, hint, options, className, ...select }:
    FieldProps & { options: readonly Option[] } & SelectHTMLAttributes<HTMLSelectElement>) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="block font-medium">{label}</label>
      <select id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy(id, error, hint)}
        className={className ?? control} {...select}>
        {options.map(option => <option key={optionValue(option)} value={optionValue(option)}>{optionLabel(option)}</option>)}
      </select>
      <Described id={id} error={error} hint={hint} />
    </div>
  );
}

/** A radiogroup named by its label, with one radio per option named by the option label. */
export function RadioGroup({ label, name, value, onChange, options, error, className }: FieldProps & {
    name: string; value: string; onChange: (value: string) => void; options: readonly Option[]; className?: string }) {
  const id = useId();
  return (
    <div role="radiogroup" aria-labelledby={id} className={className}>
      <span id={id} className="block font-medium">{label}</span>
      {options.map(option => (
        <label key={optionValue(option)} className="mr-4 inline-flex items-center gap-1">
          <input type="radio" name={name} value={optionValue(option)} checked={value === optionValue(option)}
            onChange={() => onChange(optionValue(option))} />
          {optionLabel(option)}
        </label>
      ))}
      <Described id={id} error={error} />
    </div>
  );
}

/** A checkbox named by its whole label text. */
export function Checkbox({ label, error, className, ...input }:
    { label: string; error?: string } & Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const id = useId();
  return (
    <div className={className}>
      <label className="inline-flex items-start gap-2">
        <input type="checkbox" aria-invalid={error ? true : undefined} {...input} />
        <span>{label}</span>
      </label>
      <Described id={id} error={error} />
    </div>
  );
}

/** The single alert of a form: rendered only while there is a message. */
export function FormError({ message, className }: { message?: string | null; className?: string }) {
  return message ? <p role="alert" className={className ?? "rounded bg-red-50 px-3 py-2 text-red-700"}>{message}</p> : null;
}

/** A submit button named by its text; disabled while `busy`. */
export function SubmitButton({ busy, children, className, ...button }:
    { busy?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="submit" disabled={busy || button.disabled}
      className={className ?? "rounded bg-blue-600 px-4 py-2 font-medium text-white disabled:opacity-60"} {...button}>
      {children}
    </button>
  );
}
