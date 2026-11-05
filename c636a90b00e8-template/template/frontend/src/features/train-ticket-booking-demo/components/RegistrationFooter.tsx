export type RegistrationFooterState = {  };
export type RegistrationFooterProps = {};

export function RegistrationFooter(_props: RegistrationFooterProps) {
  return (
    <footer
      data-ui-id="UI_000111"
      className="mt-10 w-full border-t border-gray-200 bg-[#f5f5f5] py-7 text-center text-[12px] leading-6 text-gray-500"
    >
      <div className="mx-auto w-full max-w-[1200px] px-4">
        <p data-ui-id="UI_000112">
          COPYRIGHT©2008-2025 CHINA ACADEMY OF RAILWAY SCIENCES CORPORATION LIMITED, ALL RIGHTS RESERVED.
        </p>
        <p data-ui-id="UI_000113">
          京公网安备 11010802038392号 | 京ICP备05020493号-4 | ICP证：京B2-20202537.
        </p>
        <div
          data-ui-id="UI_000114"
          className="mt-1 flex flex-wrap items-center justify-center gap-x-2 gap-y-1"
        >
          <a data-ui-id="UI_000115" href="#" className="transition-colors hover:text-[#2f74c0]">
            Privacy Policy
          </a>
          <span aria-hidden="true" className="text-gray-300">
            |
          </span>
          <a data-ui-id="UI_000116" href="#" className="transition-colors hover:text-[#2f74c0]">
            Cookie Statement
          </a>
        </div>
      </div>
    </footer>
  );
}
