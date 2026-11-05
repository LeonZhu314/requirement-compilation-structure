import { BrandBlock } from "./BrandBlock";
import { HeaderUtilityNav } from "./HeaderUtilityNav";

export type RegistrationHeaderState = {  };
export type RegistrationHeaderProps = {};

export function RegistrationHeader(_props: RegistrationHeaderProps) {
  return (
    <header data-ui-id="UI_000048" className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-3 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <BrandBlock />
        <div
          data-ui-id="UI_000049"
          className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-full bg-[#f6f7f9] px-5 py-2 lg:justify-end"
        >
          <nav data-ui-id="UI_000050" className="flex items-center gap-2 text-sm text-gray-700">
            <a
              data-ui-id="UI_000051"
              href="/register"
              className="transition-colors hover:text-[#2f74c0]"
            >
              Register
            </a>
            <span aria-hidden="true" className="text-gray-300">
              |
            </span>
            <a
              data-ui-id="UI_000052"
              href="/login"
              className="transition-colors hover:text-[#2f74c0]"
            >
              Login
            </a>
          </nav>
          <HeaderUtilityNav />
        </div>
      </div>
    </header>
  );
}
