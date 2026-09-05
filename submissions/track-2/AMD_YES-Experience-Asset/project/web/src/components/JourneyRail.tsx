export type JourneyView = 'm1' | 'm2' | 'm3' | 'm4' | 'm5';

export type JourneyStep = {
  id: JourneyView;
  eyebrow: string;
  title: string;
  artifact: string;
};

export const JOURNEY_STEPS: readonly JourneyStep[] = [
  { id: 'm1', eyebrow: 'M1', title: 'Frame the story', artifact: 'Experience Brief' },
  { id: 'm2', eyebrow: 'M2', title: 'Find turning points', artifact: 'Critical Moment Map' },
  { id: 'm3', eyebrow: 'M3', title: 'Trace decisions', artifact: 'Evidence Ledger' },
  { id: 'm4', eyebrow: 'M4', title: 'Extract the method', artifact: 'Insight Boundary Map' },
  { id: 'm5', eyebrow: 'M5', title: 'Create the delivery', artifact: 'Audience-ready Output' },
] as const;

export function JourneyRail({
  active,
  onSelect,
}: {
  active: JourneyView;
  onSelect: (next: JourneyView) => void;
}) {
  return (
    <nav className="journey" aria-label="Experience asset journey">
      <div className="journey__intro">
        <p className="eyebrow">Your creation path</p>
        <h2>Make hidden know-how<br />visible and reusable.</h2>
        <p>Five guided steps. Every output stays editable and recoverable.</p>
      </div>
      <ol className="journey__steps">
        {JOURNEY_STEPS.map((step, index) => {
          const current = step.id === active;
          return (
            <li key={step.id} className={current ? 'journey-step journey-step--current' : 'journey-step'}>
              <button
                type="button"
                onClick={() => onSelect(step.id)}
                aria-current={current ? 'step' : undefined}
                data-testid={`view-${step.id}`}
              >
                <span className="journey-step__index" aria-hidden="true">{index + 1}</span>
                <span className="journey-step__copy">
                  <span className="journey-step__title"><small>{step.eyebrow}</small>{step.title}</span>
                  <span className="journey-step__artifact">Output · {step.artifact}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div className="journey__privacy">
        <span aria-hidden="true">◆</span>
        <p><strong>Private by default</strong><br />Your data and inference stay in a controlled local environment.</p>
      </div>
    </nav>
  );
}
