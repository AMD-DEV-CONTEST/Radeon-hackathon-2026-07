"use strict";

const LANES = Object.freeze({
  primary: Object.freeze({
    name: "PRIMARY ADVERSARIAL",
    contexts: "384 matched pairs",
    baselineWidth: "50.5%",
    baseline: "194/384 · 50.5%",
    candidateWidth: "96.6%",
    candidate: "371/384 · 96.6%",
    added: "+177",
    lift: "+46.1 pp",
    regressions: "0",
    failures: "190 → 13"
  }),
  retention: Object.freeze({
    name: "RETENTION HELDOUT",
    contexts: "192 matched pairs",
    baselineWidth: "63.0%",
    baseline: "121/192 · 63.0%",
    candidateWidth: "100%",
    candidate: "192/192 · 100%",
    added: "+71",
    lift: "+37.0 pp",
    regressions: "0",
    failures: "71 → 0"
  })
});

const elements = Object.freeze({
  name: document.querySelector("#lane-name"),
  contexts: document.querySelector("#lane-contexts"),
  baselineBar: document.querySelector("#baseline-bar"),
  baseline: document.querySelector("#baseline-value"),
  candidateBar: document.querySelector("#candidate-bar"),
  candidate: document.querySelector("#candidate-value"),
  added: document.querySelector("#added-value"),
  lift: document.querySelector("#lift-value"),
  regressions: document.querySelector("#regression-value"),
  failures: document.querySelector("#failure-value")
});

function renderLane(key) {
  const lane = LANES[key];
  if (!lane) return;
  elements.name.textContent = lane.name;
  elements.contexts.textContent = lane.contexts;
  elements.baselineBar.style.width = lane.baselineWidth;
  elements.baseline.textContent = lane.baseline;
  elements.candidateBar.style.width = lane.candidateWidth;
  elements.candidate.textContent = lane.candidate;
  elements.added.textContent = lane.added;
  elements.lift.textContent = lane.lift;
  elements.regressions.textContent = lane.regressions;
  elements.failures.textContent = lane.failures;
  document.querySelectorAll("[data-lane]").forEach((button) => {
    const active = button.dataset.lane === key;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

document.querySelectorAll("[data-lane]").forEach((button) => {
  button.addEventListener("click", () => renderLane(button.dataset.lane));
});

document.querySelector("#year").textContent = String(new Date().getFullYear());
renderLane("primary");
