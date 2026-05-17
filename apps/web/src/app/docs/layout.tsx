import * as React from "react";
import { MarketingShell } from "@/components/MarketingShell";
import { DocsShell } from "@/components/DocsShell";

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <MarketingShell>
      <DocsShell>{children}</DocsShell>
    </MarketingShell>
  );
}
