import { NavigateToHome } from "../handlers/NavigateToHome";

export type BreadcrumbRegionState = {  };
export type BreadcrumbRegionProps = {};

export function BreadcrumbRegion(_props: BreadcrumbRegionProps) {
  return (
    <div data-ui-id="UI_000059" className="w-full bg-white">
      <div className="mx-auto w-full max-w-[1200px] px-4 py-3 text-[12px] text-gray-500 sm:px-6">
        <span data-ui-id="UI_000060">Current location:</span>{" "}
        <a
          data-ui-id="UI_000061"
          href="/"
          onClick={(event) => {
            event.preventDefault();
            void NavigateToHome({});
          }}
          className="text-[#2f74c0] hover:underline"
        >
          HOME
        </a>{" "}
        <span aria-hidden="true">&gt;</span>{" "}
        <span data-ui-id="UI_000063">Create an account</span>
      </div>
    </div>
  );
}
