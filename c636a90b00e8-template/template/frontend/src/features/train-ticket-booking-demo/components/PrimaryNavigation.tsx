function ChevronDown() {
  return (
    <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" aria-hidden="true">
      <path d="m2.5 4.25 3.5 3.5 3.5-3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export type PrimaryNavigationState = {  };
export type PrimaryNavigationProps = {};

export function PrimaryNavigation(_props: PrimaryNavigationProps) {
  return (
    <nav data-ui-id="UI_000018" className="w-full bg-[#2f74c0] text-white">
      <div className="mx-auto flex w-full max-w-[1200px] items-stretch px-4 sm:px-6">
        <a data-ui-id="UI_000019" href="/" className="border-r border-white/25 px-7 py-3 text-sm font-medium transition-colors hover:bg-[#255f9e]">
          Home
        </a>
        <a data-ui-id="UI_000020" href="#" className="flex items-center gap-1.5 border-r border-white/25 px-7 py-3 text-sm font-medium transition-colors hover:bg-[#255f9e]">
          Booking
          <ChevronDown />
        </a>
        <a data-ui-id="UI_000021" href="#" className="flex items-center gap-1.5 px-7 py-3 text-sm font-medium transition-colors hover:bg-[#255f9e]">
          Travel guides
          <ChevronDown />
        </a>
      </div>
    </nav>
  );
}
