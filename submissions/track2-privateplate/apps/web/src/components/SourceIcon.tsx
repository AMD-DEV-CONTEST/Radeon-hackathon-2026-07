import type { SVGProps } from "react";

export type SourceIconName =
  | "plate"
  | "plus"
  | "meal"
  | "family"
  | "box"
  | "mail"
  | "gear"
  | "paperclip"
  | "mic"
  | "arrowUp"
  | "x"
  | "check";

type SourceIconProps = SVGProps<SVGSVGElement> & {
  name: SourceIconName;
  size?: number;
};

export function SourceIcon({ name, size = 22, ...props }: SourceIconProps) {
  const common: SVGProps<SVGSVGElement> = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    "aria-hidden": true,
    ...props
  };

  if (name === "plate") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="8.5" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
        <path d="M4.5 8.5h15M4.5 15.5h15" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" opacity=".65" />
      </svg>
    );
  }
  if (name === "plus") {
    return (
      <svg {...common}>
        <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "meal") {
    return (
      <svg {...common}>
        <path d="M5 4v7M8 4v7M5 8h3M6.5 11v9M17 4v16M17 4c-2.2 1.9-3.2 4.4-3.2 6.6 0 1.8 1 2.7 3.2 2.7" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "family") {
    return (
      <svg {...common}>
        <circle cx="9" cy="8" r="2.7" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="16.5" cy="9" r="2.2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M3.8 18.5c.6-3 2.2-4.5 5.2-4.5s4.6 1.5 5.2 4.5M14.2 14.6c2.7-.6 4.8.7 5.7 3.9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "box") {
    return (
      <svg {...common}>
        <path d="m4.5 8 7.5-4 7.5 4v8l-7.5 4-7.5-4V8Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        <path d="m4.8 8 7.2 4 7.2-4M12 12v8" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "mail") {
    return (
      <svg {...common}>
        <rect x="4" y="5.5" width="16" height="13" rx="2.5" stroke="currentColor" strokeWidth="1.6" />
        <path d="m5.5 7.5 6.5 5 6.5-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "gear") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
        <path d="m19 13 .7 1.2-1.7 2.9-1.3-.2-.9 1.1.2 1.3-3.1 1.2-.8-1.1h-1.4l-.8 1.1-3.1-1.2.2-1.3-.9-1.1-1.3.2-1.7-2.9L5 13l-.2-1 .2-1-1.7-1.2L5 6.9l1.3.2.9-1.1L7 4.7l3.1-1.2.8 1.1h1.4l.8-1.1 3.1 1.2-.2 1.3.9 1.1 1.3-.2 1.7 2.9L19 11l.2 1-.2 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "paperclip") {
    return (
      <svg {...common}>
        <path d="m8.5 12.6 5.8-5.8a3.1 3.1 0 1 1 4.4 4.4l-7.2 7.2a4.8 4.8 0 1 1-6.8-6.8l7.1-7.1" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "mic") {
    return (
      <svg {...common}>
        <rect x="9" y="4" width="6" height="10" rx="3" stroke="currentColor" strokeWidth="1.7" />
        <path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v3M9 20h6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      </svg>
    );
  }
  if (name === "arrowUp") {
    return (
      <svg {...common}>
        <path d="M12 18V6M7.5 10.5 12 6l4.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "x") {
    return (
      <svg {...common}>
        <path d="m7 7 10 10M17 7 7 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="m6 12.5 3.8 3.8L18.5 7.8" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
