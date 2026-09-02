import { Hexagon } from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  showText?: boolean;
}

export function Logo({ className, showText = true }: LogoProps) {
  return (
    <Link href="/" className={cn("flex items-center gap-2.5", className)}>
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/20">
        <Hexagon className="h-5 w-5 fill-primary/20 text-primary" />
      </div>
      {showText ? (
        <span className="text-xl font-bold tracking-tight text-white">
          AgentVox
        </span>
      ) : null}
    </Link>
  );
}
