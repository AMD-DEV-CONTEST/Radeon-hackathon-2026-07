import { Code2, Share2, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/shared/logo";
import { LANDING_FOOTER_COLUMNS } from "@/features/marketing/constants";

const SOCIAL_LINKS: ReadonlyArray<{
  label: string;
  href: string;
  icon: LucideIcon;
}> = [
  { label: "X", href: "#", icon: X },
  { label: "GitHub", href: "#", icon: Code2 },
  { label: "LinkedIn", href: "#", icon: Share2 },
];

export function MarketingFooter() {
  return (
    <footer className="border-t border-border bg-[#050506] py-16">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <Logo />
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted-foreground">
              AI-powered multi-agent platform for conducting comprehensive
              technical interviews at scale.
            </p>
          </div>

          {LANDING_FOOTER_COLUMNS.map((column) => (
            <div key={column.title}>
              <h3 className="text-sm font-semibold text-white">{column.title}</h3>
              <ul className="mt-4 space-y-2.5">
                {column.links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-white"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-start justify-between gap-4 border-t border-border pt-8 sm:flex-row sm:items-center">
          <p className="text-xs text-muted-foreground">
            © 2026 AgentVox AI. All rights reserved.
          </p>
          <div className="flex items-center gap-4">
            {SOCIAL_LINKS.map(({ label, href, icon: Icon }) => (
              <Link
                key={label}
                href={href}
                aria-label={label}
                className="text-muted-foreground transition-colors hover:text-white"
              >
                <Icon className="h-4 w-4" />
              </Link>
            ))}
          </div>
        </div>
      </div>
    </footer>
  );
}
