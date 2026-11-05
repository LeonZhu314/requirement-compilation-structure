import { QuickGuideLinkList } from "./QuickGuideLinkList";

export type QuickGuideSectionState = {  };
export type QuickGuideSectionProps = {};

export function QuickGuideSection(_props: QuickGuideSectionProps) {
  return (
    <section data-ui-id="UI_000036" className="mx-auto w-full max-w-[1200px] px-4 pb-28 pt-16 sm:px-6">
      <h2 data-ui-id="UI_000037" className="text-[26px] font-semibold text-[#2f74c0]">
        Quick Guide
      </h2>
      <div className="mt-8">
        <QuickGuideLinkList />
      </div>
    </section>
  );
}
