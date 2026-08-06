import type { ReactNode } from 'react';

export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'muted';

export function Badge({
  tone = 'neutral',
  children,
  title,
  testId,
}: {
  tone?: Tone;
  children: ReactNode;
  title?: string;
  testId?: string;
}) {
  return (
    <span className={`badge badge--${tone}`} title={title} data-testid={testId}>
      {children}
    </span>
  );
}

export function Panel({
  title,
  children,
  testId,
  actions,
}: {
  title: string;
  children: ReactNode;
  testId?: string;
  actions?: ReactNode;
}) {
  return (
    <section className="panel" data-testid={testId} aria-label={title}>
      <header className="panel__head">
        <h2 className="panel__title">{title}</h2>
        {actions ? <div className="panel__actions">{actions}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  );
}

export function Field({
  label,
  children,
  testId,
}: {
  label: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div className="field" data-testid={testId}>
      <span className="field__label">{label}</span>
      <span className="field__value">{children}</span>
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <code className="mono">{children}</code>;
}
