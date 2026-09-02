import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement>;

function Icon({ children, ...props }: Props & { children: React.ReactNode }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{children}</svg>;
}

export function ArrowIcon(props: Props) {
  return <Icon {...props}><path d="M5 12h14M13 6l6 6-6 6" /></Icon>;
}

export function BookIcon(props: Props) {
  return <Icon {...props}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5zM20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 1 2.5 2.5z" /></Icon>;
}

export function CheckIcon(props: Props) {
  return <Icon {...props}><path d="m5 12 4 4L19 6" /></Icon>;
}

export function ChipIcon(props: Props) {
  return <Icon {...props}><rect x="7" y="7" width="10" height="10" rx="2" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" /></Icon>;
}

export function CloseIcon(props: Props) {
  return <Icon {...props}><path d="m6 6 12 12M18 6 6 18" /></Icon>;
}

export function DocumentIcon(props: Props) {
  return <Icon {...props}><path d="M6 2h8l4 4v16H6zM14 2v5h4M9 12h6M9 16h6" /></Icon>;
}

export function FlaskIcon(props: Props) {
  return <Icon {...props}><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3M7.5 15h9" /></Icon>;
}

export function MenuIcon(props: Props) {
  return <Icon {...props}><path d="M4 7h16M4 12h16M4 17h16" /></Icon>;
}

export function ReceiptIcon(props: Props) {
  return <Icon {...props}><path d="M6 2h12v20l-3-2-3 2-3-2-3 2zM9 7h6M9 11h6M9 15h3" /></Icon>;
}

export function ShieldIcon(props: Props) {
  return <Icon {...props}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="m9 12 2 2 4-5" /></Icon>;
}

export function SparkIcon(props: Props) {
  return <Icon {...props}><path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5z" /></Icon>;
}
