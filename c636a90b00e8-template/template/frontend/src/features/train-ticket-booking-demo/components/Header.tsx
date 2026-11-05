import { BrandBlock } from "./BrandBlock";
import { HeaderUtilityNav } from "./HeaderUtilityNav";
import { HeaderAccountArea } from "./HeaderAccountArea";
import type { SessionState } from "../handlers/LoadSessionState";

export type HeaderState = {  };
export type HeaderProps = {
  session: SessionState;
  onSignOut: () => void;
};

export function Header({ session, onSignOut }: HeaderProps) {
  return (
    <header data-ui-id="UI_000002" className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-3 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
        <BrandBlock />
        <div className="flex flex-wrap items-center gap-x-8 gap-y-2 lg:justify-end">
          <HeaderUtilityNav />
          <HeaderAccountArea session={session} onSignOut={onSignOut} />
        </div>
      </div>
    </header>
  );
}
