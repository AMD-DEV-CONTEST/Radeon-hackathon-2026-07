import type { ScenarioControl } from "../types";
import { ArrowIcon, FlaskIcon } from "./Icons";

type Props = {
  question: string;
  scenario: ScenarioControl;
  running: boolean;
  onQuestion: (value: string) => void;
  onScenario: (value: ScenarioControl) => void;
  onRun: () => void;
};

export function ScenarioBar({ question, scenario, running, onQuestion, onScenario, onRun }: Props) {
  return (
    <section className="query-lab" aria-labelledby="query-title">
      <div className="query-heading">
        <div><span className="eyebrow">Research brief</span><h1 id="query-title">Ask a harder question.</h1></div>
        <span className="scenario-label"><FlaskIcon /> Scenario lab</span>
      </div>
      <label className="question-field">
        <span className="sr-only">Investor research question</span>
        <textarea value={question} onChange={(event) => onQuestion(event.target.value)} rows={3} maxLength={1600} disabled={running} />
      </label>
      <div className="scenario-controls">
        <Segmented
          label="Rate path"
          value={scenario.rates}
          options={[{ value: "higher_for_longer", label: "Higher for longer" }, { value: "easing", label: "Easing" }]}
          onChange={(rates) => onScenario({ ...scenario, rates: rates as ScenarioControl["rates"] })}
        />
        <Segmented
          label="AI spending"
          value={scenario.ai_spending}
          options={[{ value: "slower", label: "Slower" }, { value: "resilient", label: "Resilient" }]}
          onChange={(ai_spending) => onScenario({ ...scenario, ai_spending: ai_spending as ScenarioControl["ai_spending"] })}
        />
        <button className="run-button" onClick={onRun} disabled={running || question.trim().length === 0}>
          {running ? "Researching locally" : "Forge analysis"}<ArrowIcon />
        </button>
      </div>
    </section>
  );
}

function Segmented({ label, value, options, onChange }: { label: string; value: string; options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) {
  return (
    <fieldset className="segmented">
      <legend>{label}</legend>
      <div>{options.map((option) => (
        <button type="button" key={option.value} aria-pressed={value === option.value} onClick={() => onChange(option.value)}>{option.label}</button>
      ))}</div>
    </fieldset>
  );
}
