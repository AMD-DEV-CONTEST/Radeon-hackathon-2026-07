import type {SVGProps} from "react";

export type IconName =
  | "arrow"
  | "check"
  | "chevron"
  | "close"
  | "code"
  | "cpu"
  | "frame"
  | "image"
  | "layers"
  | "lock"
  | "menu"
  | "palette"
  | "refresh"
  | "review"
  | "shield"
  | "sparkles"
  | "upload";

const paths:Record<IconName,React.ReactNode>={
  arrow:<><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></>,
  check:<path d="m5 12 4 4L19 6"/>,
  chevron:<path d="m9 18 6-6-6-6"/>,
  close:<><path d="m6 6 12 12"/><path d="M18 6 6 18"/></>,
  code:<><path d="m8 9-4 3 4 3"/><path d="m16 9 4 3-4 3"/><path d="m14 5-4 14"/></>,
  cpu:<><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/><rect x="10" y="10" width="4" height="4" rx=".5"/></>,
  frame:<><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 7h8M8 17h8"/></>,
  image:<><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m4 17 5-4 3 3 3-2 5 4"/></>,
  layers:<><path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/></>,
  lock:<><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/><path d="M12 14v3"/></>,
  menu:<><path d="M4 7h16M4 12h16M4 17h16"/></>,
  palette:<><path d="M12 3a9 9 0 1 0 0 18h1.5a2 2 0 0 0 0-4H12a2 2 0 0 1 0-4h3a6 6 0 0 0 0-12h-3Z"/><circle cx="7.5" cy="10" r=".8" fill="currentColor" stroke="none"/><circle cx="9.5" cy="6.8" r=".8" fill="currentColor" stroke="none"/><circle cx="14" cy="6.5" r=".8" fill="currentColor" stroke="none"/></>,
  refresh:<><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M6.1 9a7 7 0 0 1 11.5-2L20 9M4 15l2.4 2a7 7 0 0 0 11.5-2"/></>,
  review:<><path d="M9 11.5 11 14l4-5"/><path d="M12 2 4 5v6c0 5 3.4 9 8 11 4.6-2 8-6 8-11V5l-8-3Z"/></>,
  shield:<><path d="M12 2 4 5v6c0 5 3.4 9 8 11 4.6-2 8-6 8-11V5l-8-3Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></>,
  sparkles:<><path d="m12 2 1.3 4.2L17.5 7.5l-4.2 1.3L12 13l-1.3-4.2-4.2-1.3 4.2-1.3L12 2Z"/><path d="m19 14 .8 2.2L22 17l-2.2.8L19 20l-.8-2.2L16 17l2.2-.8L19 14Z"/><path d="m5 14 .7 1.8 1.8.7-1.8.7L5 19l-.7-1.8-1.8-.7 1.8-.7L5 14Z"/></>,
  upload:<><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/></>,
};

export function Icon({name,className="",...props}:{name:IconName;className?:string}&SVGProps<SVGSVGElement>){
  return <svg className={`icon ${className}`.trim()} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
