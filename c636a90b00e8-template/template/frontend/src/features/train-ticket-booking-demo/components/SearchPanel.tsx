import { useState } from "react";

function InfoIcon() {
  return (
    <svg viewBox="0 0 18 18" className="mt-0.5 h-4 w-4 flex-none text-gray-400" fill="none" aria-hidden="true">
      <circle cx="9" cy="9" r="7" stroke="currentColor" strokeWidth="1.4" />
      <path d="M9 8v4M9 5.6v.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 18 18" className="h-4 w-4" fill="none" aria-hidden="true">
      <path d="M9 16s5-4.6 5-9A5 5 0 0 0 4 7c0 4.4 5 9 5 9Z" stroke="currentColor" strokeWidth="1.4" />
      <circle cx="9" cy="7" r="1.7" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 18 18" className="h-4 w-4" fill="none" aria-hidden="true">
      <rect x="3" y="4.5" width="12" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M6 3v3M12 3v3M3 8h12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function SwapIcon() {
  return (
    <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none" aria-hidden="true">
      <path d="M6 7h9m0 0-2.5-2.5M15 7l-2.5 2.5M14 13H5m0 0 2.5-2.5M5 13l2.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const fieldClass = "h-[52px] w-full rounded border border-gray-300 bg-white pl-10 pr-3 text-base text-gray-900 outline-none transition-colors focus:border-[#2f74c0] focus:ring-1 focus:ring-[#2f74c0]/30";

export type SearchPanelState = {  };
export type SearchPanelProps = {};

export function SearchPanel(_props: SearchPanelProps) {
  const [from, setFrom] = useState("Beijing(北京)");
  const [to, setTo] = useState("Shanghai(上海)");
  const [date, setDate] = useState("Fri, May 29");

  const swapStations = () => {
    setFrom(to);
    setTo(from);
  };

  return (
    <section data-ui-id="UI_000028" className="rounded-xl bg-white p-5 shadow-[0_16px_50px_rgba(15,23,42,0.20)] sm:p-7 lg:p-8">
      <div className="flex items-start gap-3 text-[13px] leading-relaxed text-gray-500">
        <InfoIcon />
        <p>
          The 12306.cn website provides information query and ticket refund services 24 hours a day, and the ticket sales and endorsement services from 5:00 to 1:00 the next day (5:00 to 23:30 on Tuesday).
        </p>
      </div>

      <form className="mt-5" onSubmit={(event) => event.preventDefault()}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <div className="min-w-0 flex-1">
            <label htmlFor="home-from" className="mb-1 block text-xs text-gray-500">
              From
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                <PinIcon />
              </span>
              <input
                id="home-from"
                data-ui-id="UI_000030"
                type="text"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
                className={fieldClass}
              />
            </div>
          </div>

          <div className="flex justify-center pb-1 lg:pb-2">
            <button
              data-ui-id="UI_000031"
              type="button"
              aria-label="Swap stations"
              onClick={swapStations}
              className="flex h-10 w-10 items-center justify-center rounded-full bg-[#f28a2e] text-white shadow-sm transition-colors hover:bg-[#dc7720]"
            >
              <SwapIcon />
            </button>
          </div>

          <div className="min-w-0 flex-1">
            <label htmlFor="home-to" className="mb-1 block text-xs text-gray-500">
              To
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                <PinIcon />
              </span>
              <input
                id="home-to"
                data-ui-id="UI_000032"
                type="text"
                value={to}
                onChange={(event) => setTo(event.target.value)}
                className={fieldClass}
              />
            </div>
          </div>

          <div className="min-w-0 flex-1">
            <label htmlFor="home-date" className="mb-1 block text-xs text-gray-500">
              Date
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
                <CalendarIcon />
              </span>
              <input
                id="home-date"
                data-ui-id="UI_000033"
                type="text"
                value={date}
                onChange={(event) => setDate(event.target.value)}
                className={fieldClass}
              />
            </div>
          </div>

          <div className="flex-none lg:pl-1">
            <button
              data-ui-id="UI_000034"
              type="submit"
              className="h-[52px] w-full rounded bg-[#f28a2e] px-9 text-base font-semibold text-white shadow-sm transition-colors hover:bg-[#dc7720]"
            >
              Search
            </button>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-2">
          <input
            id="high-speed-only"
            data-ui-id="UI_000035"
            type="checkbox"
            className="h-4 w-4 rounded border-gray-400 text-[#2f74c0] accent-[#2f74c0]"
          />
          <label htmlFor="high-speed-only" className="text-sm text-gray-600">
            High-speed trains only
          </label>
        </div>
      </form>
    </section>
  );
}
