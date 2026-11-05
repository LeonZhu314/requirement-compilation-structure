export type BannerIndicatorsState = {  };
export type BannerIndicatorsProps = {};

const indicators = ["Show banner 1", "Show banner 2", "Show banner 3"];

export function BannerIndicators(_props: BannerIndicatorsProps) {
  return (
    <div data-ui-id="UI_000024" className="absolute bottom-[9.5rem] left-6 z-10 flex items-center gap-3 md:left-16 lg:left-[calc((100%-1200px)/2+24px)]">
      {indicators.map((label, index) => (
        <button
          key={label}
          type="button"
          aria-label={label}
          aria-pressed={index === 0}
          data-ui-id={index === 0 ? "UI_000025" : index === 1 ? "UI_000026" : "UI_000027"}
          className={index === 0 ? "h-2.5 w-2.5 rounded-full bg-white shadow-sm" : "h-2.5 w-2.5 rounded-full bg-white/40 transition-colors hover:bg-white/70"}
        />
      ))}
    </div>
  );
}
