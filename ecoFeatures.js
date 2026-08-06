/**
 * ecoFeatures.js  (classic script — shares global scope with the big
 * inline <script> in index.html, so `state`, `qState`, `SYLLABUS`,
 * `findAnswer`, `toast`, etc. are all reachable here as free variables.)
 * ------------------------------------------------------------
 * Wires in:
 *   - Local Recommendation card   (wraps showResult, 100% rule-based —
 *                                   no external AI API of any kind)
 *   - Adaptive Learning pace      (wraps renderDashboard / doLogin,
 *                                   powered by the in-browser TensorFlow.js
 *                                   model in js/adaptiveML.js)
 *
 * Note: the EcoTutor chat itself (window.sendChat) is NOT overridden here.
 * The chat already works entirely offline via the local knowledge base
 * (findAnswer / generateContextualAnswer / turtleFallback, defined in the
 * inline <script> of index.html) — no API key, no network call, needed.
 * ------------------------------------------------------------
 */

// =========================================================
// 1. Local Recommendation card after a quiz + Adaptive Learning nudge
// =========================================================
const _origShowResult = window.showResult;
window.showResult = function () {
  _origShowResult();
  setTimeout(enhanceResultWithRecommendation, 30);
};

/**
 * Builds a short, encouraging recommendation using simple rules based on
 * the student's score percentage and (if available) the local AdaptiveML
 * risk prediction. No network call — pure JS template logic.
 */
function buildLocalRecommendation({ pct, prediction, lvlName }) {
  const risk = prediction ? prediction.risk : null;

  if (pct === 100) {
    return `Perfect score on "${lvlName}"! 🌟 You've fully mastered this topic — move on to the next level with confidence.`;
  }
  if (pct >= 80) {
    return `Great work on "${lvlName}" (${pct}%)! 🐢 You clearly understand the core ideas — a quick review of the questions you missed will get you to full mastery.`;
  }
  if (pct >= 60) {
    return `Solid pass on "${lvlName}" (${pct}%) 👍 You're on track. Revisit the explanations for any wrong answers before moving ahead.`;
  }
  if (risk === "high") {
    return `"${lvlName}" was tricky this time (${pct}%). 🔁 Take a breather, re-read the syllabus notes for this level, and try again — you've got this!`;
  }
  return `Keep practicing "${lvlName}" (${pct}%) 💪 Replay the level and pay close attention to the explanation shown after each question — that's the fastest way to improve.`;
}

function enhanceResultWithRecommendation() {
  const wrap = document.querySelector(".result-screen-wrap");
  if (!wrap || !qState || !qState.qs) return;

  let prediction = null;
  if (window.AdaptiveML) {
    const feats = window.AdaptiveML.featuresFromLocalState(state);
    prediction = window.AdaptiveML.predict(feats);
  }

  // Adaptive pace badge next to the result title
  if (prediction) {
    const diff = window.AdaptiveML.nextDifficulty(prediction);
    const titleEl = wrap.querySelector(".result-title");
    if (titleEl && !titleEl.querySelector(".adaptive-badge")) {
      const badgeEl = document.createElement("span");
      badgeEl.className = "adaptive-badge adaptive-" + diff;
      badgeEl.textContent =
        diff === "accelerate" ? "🚀 Ready to accelerate" : diff === "remedial" ? "🔁 Needs review" : "➡️ On track";
      titleEl.appendChild(badgeEl);
    }
  }

  const total = qState.qs.length;
  const pct = total ? Math.round((qState.score / total) * 100) : 0;
  const recommendation = buildLocalRecommendation({ pct, prediction, lvlName: qState.lvlName });

  const card = document.createElement("div");
  card.className = "recommend-card";
  card.innerHTML = `<div class="recommend-card-title">🐢 Recommendation</div><div class="recommend-card-body">${recommendation}</div>`;
  const badgeBox = wrap.querySelector(".result-badge");
  if (badgeBox) badgeBox.insertAdjacentElement("afterend", card);
}

// =========================================================
// 2. Adaptive Learning pace indicator on the dashboard
// (Powered entirely by the in-browser TensorFlow.js model in
// js/adaptiveML.js, trained on this device from Firestore quiz history —
// no server-side ML, no external AI API.)
// =========================================================
const _origRenderDashboard = window.renderDashboard;
window.renderDashboard = function () {
  _origRenderDashboard();
  renderAdaptivePaceBadge();
};

function renderAdaptivePaceBadge() {
  const greeting = document.querySelector(".dash-greeting");
  if (!greeting || !window.AdaptiveML || !window.AdaptiveML.isReady()) return;
  const feats = window.AdaptiveML.featuresFromLocalState(state);
  const pred = window.AdaptiveML.predict(feats);
  const diff = window.AdaptiveML.nextDifficulty(pred);
  const label =
    diff === "accelerate" ? "🚀 Accelerated Pace" : diff === "remedial" ? "🔁 Extra Practice Recommended" : "➡️ Steady Pace";
  let el = document.getElementById("adaptive-pace-badge");
  if (!el) {
    el = document.createElement("span");
    el.id = "adaptive-pace-badge";
    greeting.appendChild(el);
  }
  el.className = "adaptive-badge adaptive-" + diff;
  el.textContent = label;
}

const _origDoLogin = window.doLogin;
window.doLogin = function () {
  _origDoLogin();
  if (window.AdaptiveML) {
    window.AdaptiveML.init().then(() => {
      if (typeof renderDashboard === "function" && document.getElementById("view-dashboard")) {
        renderDashboard();
        renderAdaptivePaceBadge();
      }
    });
  }
};
