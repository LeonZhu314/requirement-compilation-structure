export type RegistrationFormValues = {
  nationality: string;
  name: string;
  passport_number: string;
  passport_expiration_date: string;
  date_of_birth: string;
  gender: string;
  username: string;
  password: string;
  confirm_password: string;
  email: string;
  agreed_to_terms: boolean;
};

export type RegistrationFormState = {  };
export type RegistrationFormProps = {
  values: RegistrationFormValues;
  errorMessage: string | null;
  submitting: boolean;
  onChange: (field: keyof RegistrationFormValues, value: string | boolean) => void;
  onSubmit: () => void;
};

const inputClass =
  "h-9 w-full rounded-[3px] border border-gray-300 bg-white px-3 text-sm text-gray-900 outline-none placeholder:text-gray-400 focus:border-[#2f74c0] focus:ring-1 focus:ring-[#2f74c0]/30";
const labelClass = "w-[190px] shrink-0 pt-2 text-right text-sm text-gray-700";
const helperClass = "pt-2 text-[12px] leading-5";

function RequiredMark() {
  return (
    <span aria-hidden="true" className="mr-0.5 text-[#c62430]">
      *
    </span>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
      <rect x="3.2" y="4.4" width="13.6" height="12.2" rx="1.6" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3.4 7.8h13.2M6.8 2.9v3M13.2 2.9v3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

type DateFieldProps = {
  id: string;
  uiId: string;
  buttonUiId: string;
  buttonLabel: string;
  value: string;
  onChange: (value: string) => void;
};

function DateField({ id, uiId, buttonUiId, buttonLabel, value, onChange }: DateFieldProps) {
  return (
    <div className="relative w-[365px]">
      <input
        id={id}
        data-ui-id={uiId}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="yyyy-mm-dd"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={`${inputClass} pr-10`}
      />
      <button
        type="button"
        data-ui-id={buttonUiId}
        aria-label={buttonLabel}
        onClick={() => document.getElementById(id)?.focus()}
        className="absolute right-0 top-0 flex h-9 w-9 items-center justify-center text-gray-500 transition-colors hover:text-[#2f74c0]"
      >
        <CalendarIcon />
      </button>
    </div>
  );
}

export function RegistrationForm({
  values,
  errorMessage,
  submitting,
  onChange,
  onSubmit,
}: RegistrationFormProps) {
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <form data-ui-id="UI_000065" noValidate onSubmit={handleSubmit} className="w-full">
      <div className="flex flex-col gap-5">
        {/* Nationality */}
        <div data-ui-id="UI_000066" className="flex flex-wrap items-start gap-4">
          <label htmlFor="reg-nationality" className={labelClass}>
            <RequiredMark />
            <span>Nationality</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <select
              id="reg-nationality"
              data-ui-id="UI_000068"
              value={values.nationality}
              onChange={(event) => onChange("nationality", event.target.value)}
              className={`${inputClass} appearance-none bg-[linear-gradient(45deg,transparent_50%,#6b7280_50%),linear-gradient(135deg,#6b7280_50%,transparent_50%)] bg-[length:5px_5px,5px_5px] bg-[position:calc(100%-16px)_center,calc(100%-11px)_center] bg-no-repeat pr-9`}
            >
              <option data-ui-id="UI_000070" value="">
                Please select
              </option>
              <option data-ui-id="UI_000069" value="Vietnam">
                Vietnam
              </option>
            </select>
          </div>
          <p className={`${helperClass} text-[#d9820a]`}>
            At present, only foreign passports are accepted for registration.
          </p>
        </div>

        {/* Name */}
        <div className="flex flex-wrap items-start gap-4">
          <label htmlFor="reg-name" className={labelClass}>
            <RequiredMark />
            <span>Name</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <input
              id="reg-name"
              data-ui-id="UI_000073"
              type="text"
              autoComplete="off"
              value={values.name}
              onChange={(event) => onChange("name", event.target.value)}
              className={inputClass}
            />
          </div>
          <a
            data-ui-id="UI_000074"
            href="#"
            className={`${helperClass} text-[#2f74c0] underline hover:text-[#255f9e]`}
          >
            Check the rules for filling out passport information
          </a>
        </div>

        {/* Passport number */}
        <div className="flex items-start gap-4">
          <label htmlFor="reg-passport-number" className={labelClass}>
            <RequiredMark />
            <span>Passport number</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <input
              id="reg-passport-number"
              data-ui-id="UI_000077"
              type="text"
              autoComplete="off"
              value={values.passport_number}
              onChange={(event) => onChange("passport_number", event.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {/* Passport expiration date */}
        <div className="flex items-start gap-4">
          <label htmlFor="reg-passport-expiration" className={labelClass}>
            <RequiredMark />
            <span>Passport expiration date</span>
            <span aria-hidden="true">:</span>
          </label>
          <DateField
            id="reg-passport-expiration"
            uiId="UI_000080"
            buttonUiId="UI_000081"
            buttonLabel="Choose passport expiration date"
            value={values.passport_expiration_date}
            onChange={(value) => onChange("passport_expiration_date", value)}
          />
        </div>

        {/* Date of birth */}
        <div className="flex items-start gap-4">
          <label htmlFor="reg-date-of-birth" className={labelClass}>
            <RequiredMark />
            <span>Date of birth</span>
            <span aria-hidden="true">:</span>
          </label>
          <DateField
            id="reg-date-of-birth"
            uiId="UI_000084"
            buttonUiId="UI_000085"
            buttonLabel="Choose date of birth"
            value={values.date_of_birth}
            onChange={(value) => onChange("date_of_birth", value)}
          />
        </div>

        {/* Gender */}
        <div className="flex items-start gap-4">
          <span id="reg-gender-label" className={labelClass}>
            <RequiredMark />
            <span>Gender</span>
            <span aria-hidden="true">:</span>
          </span>
          <div
            role="radiogroup"
            aria-labelledby="reg-gender-label"
            data-ui-id="UI_000088"
            className="flex w-[365px] gap-3"
          >
            <label className="flex flex-1 cursor-pointer items-center gap-2 rounded-[3px] border border-gray-300 bg-[#fafafa] px-3 py-2 text-sm text-gray-700">
              <input
                data-ui-id="UI_000089"
                type="radio"
                name="gender"
                value="Male"
                checked={values.gender === "Male"}
                onChange={() => onChange("gender", "Male")}
                className="h-4 w-4"
              />
              Male
            </label>
            <label className="flex flex-1 cursor-pointer items-center gap-2 rounded-[3px] border border-gray-300 bg-[#fafafa] px-3 py-2 text-sm text-gray-700">
              <input
                data-ui-id="UI_000090"
                type="radio"
                name="gender"
                value="Female"
                checked={values.gender === "Female"}
                onChange={() => onChange("gender", "Female")}
                className="h-4 w-4"
              />
              Female
            </label>
          </div>
        </div>

        {/* Username */}
        <div className="flex items-start gap-4">
          <label htmlFor="reg-username" className={labelClass}>
            <RequiredMark />
            <span>Username</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <input
              id="reg-username"
              data-ui-id="UI_000093"
              type="text"
              autoComplete="username"
              value={values.username}
              onChange={(event) => onChange("username", event.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {/* Password */}
        <div className="flex items-start gap-4">
          <label htmlFor="reg-password" className={labelClass}>
            <RequiredMark />
            <span>Password</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <input
              id="reg-password"
              data-ui-id="UI_000096"
              type="password"
              autoComplete="new-password"
              value={values.password}
              onChange={(event) => onChange("password", event.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {/* Confirm Password */}
        <div className="flex items-start gap-4">
          <label htmlFor="reg-confirm-password" className={labelClass}>
            <RequiredMark />
            <span>Confirm Password</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <input
              id="reg-confirm-password"
              data-ui-id="UI_000099"
              type="password"
              autoComplete="new-password"
              value={values.confirm_password}
              onChange={(event) => onChange("confirm_password", event.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {/* Email address */}
        <div className="flex flex-wrap items-start gap-4">
          <label htmlFor="reg-email" className={labelClass}>
            <RequiredMark />
            <span>Email address</span>
            <span aria-hidden="true">:</span>
          </label>
          <div className="w-[365px]">
            <input
              id="reg-email"
              data-ui-id="UI_000102"
              type="text"
              autoComplete="email"
              value={values.email}
              onChange={(event) => onChange("email", event.target.value)}
              className={inputClass}
            />
          </div>
          <p className={`${helperClass} text-[#d9820a]`}>
            Related notifications will be sent to you via email.
          </p>
        </div>
      </div>

      {/* Consent */}
      <div className="mt-8 flex justify-center">
        <div className="flex w-full max-w-[660px] items-start gap-2 text-[13px] leading-5 text-gray-700">
          <input
            id="reg-agreement"
            data-ui-id="UI_000105"
            type="checkbox"
            checked={values.agreed_to_terms}
            onChange={(event) => onChange("agreed_to_terms", event.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 rounded-sm border border-gray-400"
          />
          <label data-ui-id="UI_000106" htmlFor="reg-agreement" className="cursor-pointer">
            I have read and agree to abide by{" "}
            <a data-ui-id="UI_000107" href="#" className="text-[#2f74c0] underline hover:text-[#255f9e]">
              Terms of Service
            </a>{" "}
            and{" "}
            <a data-ui-id="UI_000108" href="#" className="text-[#2f74c0] underline hover:text-[#255f9e]">
              Privacy Policy
            </a>{" "}
            of 12306.cn.
          </label>
        </div>
      </div>

      {errorMessage ? (
        <div
          role="alert"
          data-ui-id="UI_000109"
          className="mx-auto mt-5 max-w-[660px] rounded-[3px] border border-[#f0c2c2] bg-[#fdf3f3] px-4 py-2 text-[13px] text-[#c0392b]"
        >
          {errorMessage}
        </div>
      ) : null}

      <div className="mt-6 flex justify-center">
        <button
          data-ui-id="UI_000110"
          type="submit"
          disabled={submitting}
          className="h-10 w-[280px] rounded-[3px] bg-[#f08300] text-[15px] font-medium text-white transition-colors hover:bg-[#d97400] disabled:cursor-not-allowed disabled:opacity-70"
        >
          Next step
        </button>
      </div>
    </form>
  );
}
