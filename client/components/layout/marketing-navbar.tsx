"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Logo } from "@/components/shared/logo";
import { Button, buttonVariants } from "@/components/ui/button";
import { LANDING_NAV_LINKS } from "@/features/marketing/constants";
import { cn } from "@/lib/utils";

export function MarketingNavbar() {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <header className="fixed top-0 z-50 w-full border-b border-border/50 bg-background/80 backdrop-blur-xl">
      <nav
        aria-label="Primary"
        className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6"
      >
        <Logo />

        <div className="hidden items-center gap-8 md:flex">
          {LANDING_NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-muted-foreground transition-colors hover:text-white"
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="hidden items-center gap-3 md:flex">
          <Link
            href="/login"
            className="text-sm text-muted-foreground transition-colors hover:text-white"
          >
            Log In
          </Link>
          <Link
            href="/register"
            className={cn(
              buttonVariants({ size: "sm" }),
              "h-9 px-4 glow-purple"
            )}
          >
            Get Started
          </Link>
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-expanded={isOpen}
          aria-controls="mobile-nav"
          aria-label={isOpen ? "Close menu" : "Open menu"}
          onClick={() => setIsOpen((prev) => !prev)}
        >
          {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </Button>
      </nav>

      {isOpen ? (
        <div
          id="mobile-nav"
          className="border-t border-border/50 bg-background/95 px-4 py-4 md:hidden"
        >
          <div className="flex flex-col gap-3">
            {LANDING_NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-white"
                onClick={() => setIsOpen(false)}
              >
                {link.label}
              </Link>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-border/50 pt-4">
              <Link
                href="/login"
                className="rounded-lg px-3 py-2 text-sm text-muted-foreground hover:text-white"
                onClick={() => setIsOpen(false)}
              >
                Log In
              </Link>
              <Link
                href="/register"
                className={cn(
                  buttonVariants({ size: "lg" }),
                  "h-10 justify-center"
                )}
                onClick={() => setIsOpen(false)}
              >
                Get Started
              </Link>
            </div>
          </div>
        </div>
      ) : null}
    </header>
  );
}
