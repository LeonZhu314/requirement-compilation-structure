const linkClass = "inline-flex items-start gap-3 text-[15px] leading-6 text-gray-700 transition-colors hover:text-[#2f74c0]";

function Bullet() {
  return <span aria-hidden="true" className="mt-[9px] h-2 w-2 flex-none bg-[#2f74c0]" />;
}

export type QuickGuideLinkListState = {  };
export type QuickGuideLinkListProps = {};

export function QuickGuideLinkList(_props: QuickGuideLinkListProps) {
  return (
    <div data-ui-id="UI_000038" className="grid gap-10 md:grid-cols-2 md:gap-24">
      <div className="space-y-6">
        <a data-ui-id="UI_000040" href="#" className={linkClass}>
          <Bullet />
          <span>What ID documents are accepted by 12306.cn English website?</span>
        </a>
        <a data-ui-id="UI_000039" href="#" className={linkClass}>
          <Bullet />
          <span>What services does 12306.cn English website provide?</span>
        </a>
      </div>
      <div>
        <div className="space-y-6">
          <a href="#" className={linkClass}>
            <Bullet />
            <span>What is endorsement?</span>
          </a>
          <a href="#" className={linkClass}>
            <Bullet />
            <span>What are the rules of ticket endorsement?</span>
          </a>
        </div>
        <a data-ui-id="UI_000041" href="#" className="mt-8 inline-block text-sm text-gray-400 transition-colors hover:text-[#2f74c0]">
          More&gt;
        </a>
      </div>
    </div>
  );
}
