import { BannerIndicators } from "./BannerIndicators";
import { SearchPanel } from "./SearchPanel";

export type HeroBannerState = {  };
export type HeroBannerProps = {};

export function HeroBanner(_props: HeroBannerProps) {
  return (
    <section data-ui-id="UI_000022" className="relative bg-white">
      <div
        data-ui-id="UI_000023"
        role="img"
        aria-label="Nighttime high-speed train at a station"
        className="relative h-[500px] w-full overflow-hidden bg-[#07101f]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 19% 64%, rgba(255,164,76,.75) 0, rgba(255,164,76,.16) 8%, transparent 20%), radial-gradient(circle at 31% 55%, rgba(255,188,92,.55) 0, transparent 16%), radial-gradient(circle at 73% 35%, rgba(255,174,87,.30) 0, transparent 12%), radial-gradient(circle at 86% 72%, rgba(255,144,55,.45) 0, transparent 14%), linear-gradient(180deg, #040a14 0%, #0a1628 58%, #101b2b 100%)",
        }}
      >
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-[#0c1726] to-transparent" aria-hidden="true" />
        <div className="absolute bottom-28 left-[12%] h-2 w-[74%] rounded-full bg-white/30 blur-[2px]" aria-hidden="true" />
        <div className="absolute bottom-[7.8rem] left-[18%] h-14 w-[66%] rounded-t-[50%] bg-gradient-to-r from-slate-700 via-slate-100 to-slate-600 opacity-80 shadow-[0_-10px_40px_rgba(255,255,255,.18)]" aria-hidden="true" />
        <div className="absolute bottom-[6.3rem] left-[15%] h-3 w-[70%] bg-slate-500/70" aria-hidden="true" />
        <div className="absolute left-[7%] top-[18%] h-16 w-16 rounded-full bg-amber-300/10 blur-2xl" aria-hidden="true" />
        <div className="absolute right-[12%] top-[24%] h-24 w-24 rounded-full bg-orange-300/10 blur-3xl" aria-hidden="true" />
        <BannerIndicators />
      </div>

      <div className="relative z-10 mx-auto -mt-24 w-full max-w-[1200px] px-4 pb-2 sm:px-6">
        <SearchPanel />
      </div>
    </section>
  );
}
