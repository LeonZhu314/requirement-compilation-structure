import type { SessionState } from "../handlers/LoadSessionState";

export type HeaderAccountAreaState = {  };
export type HeaderAccountAreaProps = {
  session: SessionState;
  onSignOut: () => void;
};

export function HeaderAccountArea({ session, onSignOut }: HeaderAccountAreaProps) {
  return (
    <div data-ui-id="UI_000011" className="flex items-center text-sm text-[#2f74c0]">
      {session.authenticated ? (
        <div data-ui-id="UI_000015" className="flex items-center gap-3">
          <span data-ui-id="UI_000016" className="max-w-[180px] truncate text-gray-800">
            {session.username}
          </span>
          <a
            data-ui-id="UI_000017"
            href="#"
            onClick={(event) => {
              event.preventDefault();
              onSignOut();
            }}
            className="font-medium transition-colors hover:text-[#c62430]"
          >
            Sign out
          </a>
        </div>
      ) : (
        <div data-ui-id="UI_000012" className="flex items-center gap-2">
          <a data-ui-id="UI_000013" href="/register" className="font-medium transition-colors hover:text-[#c62430]">
            Register
          </a>
          <span aria-hidden="true" className="text-gray-300">|</span>
          <a data-ui-id="UI_000014" href="/login" className="font-medium transition-colors hover:text-[#c62430]">
            Login
          </a>
        </div>
      )}
    </div>
  );
}
