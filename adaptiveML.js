/**
 * adaptiveML.js
 * ------------------------------------------------------------
 * Lightweight in-browser "Student Performance Prediction" model.
 *
 * Honesty note: there is no pre-existing trained model in this project, and
 * we don't have ground-truth labels like "this student later dropped out."
 * So this trains a small TensorFlow.js network *in the browser* on real
 * quiz-history rows pulled from Firestore (`scores` collection), using
 * transparent heuristic ("weak") labels derived from accuracy/consistency.
 * It re-trains quickly (a few hundred ms) whenever enough data exists, and
 * falls back to the heuristic directly if TF.js isn't loaded or data is
 * too sparse to train on.
 *
 * Exposes (on window.AdaptiveML):
 *   - init()                         -> loads tfjs model (trains from Firestore scores)
 *   - featuresFromLocalState(state)  -> builds a feature vector for the current student
 *   - predict(features)              -> { risk: 'low'|'medium'|'high', masteryScore: 0-100, recommendedLevel }
 *   - nextDifficulty(currentLevelId, lastScorePct, prediction) -> 'remedial' | 'normal' | 'accelerate'
 * ------------------------------------------------------------
 */
(function () {
  const AdaptiveML = {
    _model: null,
    _ready: false,
    _usingHeuristicOnly: false,
  };

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

  // ---- Feature engineering -------------------------------------------
  // features = [accuracyPct/100, levelsDone/17, streak/10, recentTrend(-1..1)]
  function buildFeatures({ accuracyPct = 0, levelsDone = 0, streak = 0, recentTrend = 0 }) {
    return [
      clamp(accuracyPct / 100, 0, 1),
      clamp(levelsDone / 17, 0, 1),
      clamp(streak / 10, 0, 1),
      clamp((recentTrend + 1) / 2, 0, 1),
    ];
  }

  function weakLabel(accuracyPct, streak) {
    // Heuristic ground truth used only to bootstrap the tiny network.
    if (accuracyPct >= 80 && streak >= 2) return [1, 0, 0]; // low risk
    if (accuracyPct >= 55) return [0, 1, 0]; // medium risk
    return [0, 0, 1]; // high risk
  }

  async function buildTrainingSetFromScores(scores) {
    // Aggregate per-student rows into feature/label pairs.
    const byStudent = {};
    scores.forEach((s) => {
      const key = s.name || "anon";
      if (!byStudent[key]) byStudent[key] = [];
      byStudent[key].push(s);
    });
    const xs = [], ys = [];
    Object.values(byStudent).forEach((rows) => {
      rows.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
      let streak = 0, prevPct = null;
      rows.forEach((r, i) => {
        const pct = r.total ? (r.score / r.total) * 100 : 0;
        streak = pct >= 60 ? streak + 1 : 0;
        const trend = prevPct === null ? 0 : clamp((pct - prevPct) / 100, -1, 1);
        xs.push(buildFeatures({
          accuracyPct: pct,
          levelsDone: i + 1,
          streak,
          recentTrend: trend,
        }));
        ys.push(weakLabel(pct, streak));
        prevPct = pct;
      });
    });
    return { xs, ys };
  }

  async function init() {
    if (typeof tf === "undefined") {
      AdaptiveML._usingHeuristicOnly = true;
      AdaptiveML._ready = true;
      return;
    }
    try {
      let scores = [];
      // window.getAllScoresForML is set by the Firestore bridge module
      // script, which may still be loading. Wait for window.EcoReady (with
      // a generous timeout so a genuinely offline/blocked Firebase load
      // still falls back to the heuristic instead of hanging forever).
      if (!window.getAllScoresForML && window.EcoReady) {
        await Promise.race([
          window.EcoReady,
          new Promise((r) => setTimeout(r, 4000)),
        ]);
      }
      if (window.getAllScoresForML) {
        scores = await window.getAllScoresForML();
      }
      if (!scores || scores.length < 8) {
        AdaptiveML._usingHeuristicOnly = true;
        AdaptiveML._ready = true;
        return;
      }
      const { xs, ys } = await buildTrainingSetFromScores(scores);
      const model = tf.sequential();
      model.add(tf.layers.dense({ inputShape: [4], units: 8, activation: "relu" }));
      model.add(tf.layers.dense({ units: 8, activation: "relu" }));
      model.add(tf.layers.dense({ units: 3, activation: "softmax" }));
      model.compile({ optimizer: tf.train.adam(0.02), loss: "categoricalCrossentropy" });

      const xsT = tf.tensor2d(xs);
      const ysT = tf.tensor2d(ys);
      await model.fit(xsT, ysT, { epochs: 30, batchSize: 16, verbose: 0 });
      xsT.dispose(); ysT.dispose();

      AdaptiveML._model = model;
      AdaptiveML._ready = true;
      console.log("🐢 AdaptiveML: trained in-browser model on", xs.length, "quiz-history samples.");
    } catch (e) {
      console.warn("AdaptiveML training failed, falling back to heuristic:", e);
      AdaptiveML._usingHeuristicOnly = true;
      AdaptiveML._ready = true;
    }
  }

  function featuresFromLocalState(state) {
    const accuracyPct = state.totalAns > 0 ? (state.totalCorrect / state.totalAns) * 100 : 0;
    return {
      accuracyPct,
      levelsDone: state.lvlsDone || 0,
      streak: state.streak || 0,
      recentTrend: state._lastTrend || 0,
    };
  }

  function heuristicPredict(f) {
    const label = weakLabel(f.accuracyPct, f.streak);
    const idx = label.indexOf(1);
    const risk = ["low", "medium", "high"][idx];
    const masteryScore = clamp(Math.round(f.accuracyPct * 0.7 + f.streak * 3), 0, 100);
    return { risk, masteryScore, recommendedLevel: risk === "low" ? "advance" : risk === "medium" ? "steady" : "remedial" };
  }

  function predict(rawFeatures) {
    const f = buildFeatures(rawFeatures);
    if (AdaptiveML._usingHeuristicOnly || !AdaptiveML._model) {
      return heuristicPredict(rawFeatures);
    }
    const t = tf.tensor2d([f]);
    const out = AdaptiveML._model.predict(t);
    const probs = out.dataSync();
    t.dispose(); out.dispose();
    const idx = probs.indexOf(Math.max(...probs));
    const risk = ["low", "medium", "high"][idx];
    const masteryScore = clamp(Math.round(probs[0] * 100), 0, 100);
    return { risk, masteryScore, recommendedLevel: risk === "low" ? "advance" : risk === "medium" ? "steady" : "remedial" };
  }

  function nextDifficulty(prediction) {
    if (prediction.risk === "high") return "remedial";
    if (prediction.risk === "low" && prediction.masteryScore >= 85) return "accelerate";
    return "normal";
  }

  window.AdaptiveML = {
    init,
    featuresFromLocalState,
    predict,
    nextDifficulty,
    isReady: () => AdaptiveML._ready,
  };
})();
