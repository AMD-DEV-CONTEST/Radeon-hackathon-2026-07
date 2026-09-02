import type { SafeEvent } from "../types";
import { CheckIcon, ChipIcon, SparkIcon } from "./Icons";

export function RunProgress({ events, running }: { events: SafeEvent[]; running: boolean }) {
  if (!running && events.length === 0) return null;
  const latest = events.at(-1);
  const completed = events.filter((event) => event.status === "completed").length;
  return (
    <section className={`run-progress ${running ? "is-running" : "is-complete"}`} aria-live="polite" aria-label="Local research progress">
      <div className="progress-orbit"><ChipIcon /><span /></div>
      <div className="progress-copy">
        <span className="eyebrow">Radeon local orchestration</span>
        <strong>{running ? latest?.label ?? "Preparing the research plan" : "Research case ready"}</strong>
        <div className="progress-track"><span style={{ width: `${Math.min(100, completed * 5)}%` }} /></div>
      </div>
      <div className="progress-count">{running ? <><SparkIcon /> {completed} verified steps</> : <><CheckIcon /> Complete</>}</div>
    </section>
  );
}
