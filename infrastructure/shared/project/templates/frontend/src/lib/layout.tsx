import type { ReactNode } from "react";

/** Page frame: optional header and footer around the main content. Restyle or replace freely. */
export function Layout({ header, footer, children, className }:
    { header?: ReactNode; footer?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={className ?? "flex min-h-screen flex-col"}>
      {header ? <header>{header}</header> : null}
      <main className="flex-1">{children}</main>
      {footer ? <footer>{footer}</footer> : null}
    </div>
  );
}
