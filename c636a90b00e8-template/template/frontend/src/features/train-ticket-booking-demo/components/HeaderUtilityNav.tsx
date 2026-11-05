function ChevronDown() {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" aria-hidden="true">
      <path d="m2.5 4.25 3.5 3.5 3.5-3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PhoneIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
      <path d="M4.3 3.5h3l1.2 3-1.8 1.4a11.3 11.3 0 0 0 5.4 5.4l1.4-1.8 3 1.2v3c0 .8-.7 1.5-1.5 1.5C8 17.2 2.8 12 2.8 5c0-.8.7-1.5 1.5-1.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}

export type HeaderUtilityNavState = {  };
export type HeaderUtilityNavProps = {};

export function HeaderUtilityNav(_props: HeaderUtilityNavProps) {
  return (
    <nav data-ui-id="UI_000007" className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-gray-700">
      <a href="#" data-ui-id="UI_000008" className="flex items-center gap-1.5 transition-colors hover:text-[#2f74c0]">
        My 12306
        <ChevronDown />
      </a>
      <button type="button" data-ui-id="UI_000009" className="flex items-center gap-1.5 text-sm text-gray-700 transition-colors hover:text-[#2f74c0]">
        简体中文
        <ChevronDown />
      </button>
      <a href="#" data-ui-id="UI_000010" className="flex items-center gap-1.5 transition-colors hover:text-[#2f74c0]">
        <PhoneIcon />
        Contact us
      </a>
    </nav>
  );
}
