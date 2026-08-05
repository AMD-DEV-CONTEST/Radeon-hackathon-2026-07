(function attachLearningCore(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.IELTSLearning = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function createLearningCore() {
  const WORD_INTERVALS = [1, 2, 4, 8, 16, 35, 70, 140, 240];
  const addDays = (date, days) => { const value = new Date(`${date}T12:00:00Z`); value.setUTCDate(value.getUTCDate() + days); return value.toISOString().slice(0, 10); };
  const normalizeDaily = (value) => { const number = Math.round(Number(value)); return Number.isFinite(number) && number >= 1 ? Math.min(200, number) : 8; };

  function normalizeProgress(raw = {}) {
    const reviewCount = Number(raw.reviewCount || 0);
    const stage = Number.isInteger(raw.stage) ? Math.max(-1, Math.min(8, raw.stage)) : reviewCount === 0 ? -1 : reviewCount <= 2 ? 0 : 1;
    return { ...raw, learningState: ["new", "learning", "review", "relearning"].includes(raw.learningState) ? raw.learningState : reviewCount ? "review" : "new", stage, ease: Math.max(1.3, Number(raw.ease || 2.5)), lapses: Math.max(0, Number(raw.lapses || 0)), leech: Boolean(raw.leech) };
  }

  function beginAppearance(word, appearanceId) {
    if (!word || !appearanceId) throw new Error("word and appearanceId are required");
    return { word, id: appearanceId, failed: false };
  }

  function recordFailure(raw, appearance, today) {
    const progress = normalizeProgress(raw);
    if (appearance.failed) return progress;
    appearance.failed = true;
    const lapses = progress.lapses + 1;
    return { ...progress, learningState: "relearning", stage: 0, ease: Math.max(1.3, Number((progress.ease - 0.2).toFixed(2))), lapses, leech: progress.leech || lapses >= 6, relearningDueDate: today };
  }

  function recordSuccess(raw, appearance, today, random = Math.random) {
    const progress = normalizeProgress(raw);
    if (appearance.failed || appearance.succeeded) return progress;
    appearance.succeeded = true;
    const stage = progress.learningState === "relearning" ? 0 : Math.min(8, progress.stage + 1);
    const jitter = 0.95 + random() * 0.10;
    const interval = Math.max(1, Math.round(WORD_INTERVALS[stage] * progress.ease / 2.5 * jitter));
    const { relearningDueDate: _, ...rest } = progress;
    return { ...rest, learningState: "review", stage, reviewDate: today, nextReviewDate: addDays(today, interval), reviewCount: Number(progress.reviewCount || 0) + 1 };
  }

  function buildDailyQueue({ words = [], progress = {}, today, daily }) {
    const normalizedDaily = normalizeDaily(daily);
    const cap = Math.max(40, normalizedDaily * 6);
    const reviewSlots = Math.floor(cap * 0.8);
    const hasProgress = (word) => progress[word] && Object.keys(progress[word]).length > 0;
    const backlog = words.filter((item) => {
      const value = progress[item.word];
      if (value?.reviewDate === today && value?.learningState !== "relearning") return false;
      return value?.learningState === "relearning" || (hasProgress(item.word) && (!value.nextReviewDate || value.nextReviewDate <= today)) || (!hasProgress(item.word) && item.memoryState === "due");
    }).sort((a, b) => {
      const left = normalizeProgress(progress[a.word]);
      const right = normalizeProgress(progress[b.word]);
      return Number(right.learningState === "relearning") - Number(left.learningState === "relearning") || right.lapses - left.lapses || String(left.nextReviewDate || "0000-00-00").localeCompare(String(right.nextReviewDate || "0000-00-00")) || left.stage - right.stage || Number(a.bookIndex || 0) - Number(b.bookIndex || 0);
    });
    const unseen = words.filter((item) => !hasProgress(item.word) && item.memoryState !== "due").sort((a, b) => Number(a.bookIndex || 0) - Number(b.bookIndex || 0));
    const reviews = backlog.slice(0, reviewSlots);
    const fresh = unseen.slice(0, Math.min(normalizedDaily, cap - reviews.length));
    const deferredReview = backlog.length - reviews.length;
    return { words: [...reviews, ...fresh].map((item) => item.word), fresh: fresh.map((item) => item.word), review: reviews.map((item) => item.word), cap, reviewSlots, deferredReview, deferred: deferredReview + unseen.length - fresh.length };
  }

  const projectionDays = ({ remainingUnseen, daily, deferredReview, reviewSlots }) => Math.ceil(remainingUnseen / normalizeDaily(daily)) + Math.ceil(deferredReview / Math.max(1, reviewSlots));

  const realDate = (value) => { const date = /^\d{4}-\d{2}-\d{2}$/.test(value || "") ? new Date(`${value}T12:00:00Z`) : null; return date && !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value; };
  const validStreak = (value, today) => Number.isInteger(value?.count) && value.count >= 1 && realDate(value.lastActiveDate) && value.lastActiveDate <= today;
  function migrateStreak(stored, events = [], today) {
    if (validStreak(stored, today)) return stored;
    const dates = new Set(events.filter((event) => Number(event.durationMinutes) > 0 && event.activity !== "首次基线诊断").map((event) => event.date || String(event.createdAt || "").slice(0, 10)).filter((date) => realDate(date) && date <= today));
    let date = dates.has(today) ? today : dates.has(addDays(today, -1)) ? addDays(today, -1) : null;
    if (!date) return null;
    const lastActiveDate = date;
    let count = 0;
    while (dates.has(date)) { count += 1; date = addDays(date, -1); }
    return { count, lastActiveDate };
  }
  function advanceStreak(stored, today) {
    if (!validStreak(stored, today)) return { count: 1, lastActiveDate: today };
    if (stored.lastActiveDate === today) return stored;
    return { count: addDays(stored.lastActiveDate, 1) === today ? stored.count + 1 : 1, lastActiveDate: today };
  }

  const MODULES = ["Listening", "Reading", "Writing", "Speaking"];
  const roundBand = (value) => Math.round(value * 2) / 2;
  const accuracyToBand = (ratio) => ratio >= .9 ? 8 : ratio >= .8 ? 7.5 : ratio >= .7 ? 6.5 : ratio >= .6 ? 6 : ratio >= .5 ? 5.5 : ratio >= .4 ? 5 : 4.5;
  function isCalibrationEvent(event) {
    if (!event || event.activity === "首次基线诊断" || Number(event.maxScore) <= 0) return false;
    if (["Listening", "Reading"].includes(event.module)) return event.evidenceType === "objective" || Number(event.maxScore) >= 10 && new RegExp(`^${event.module.toLowerCase()}-\\d+-\\d+-\\d+`).test(String(event.sourceId || ""));
    return ["Writing", "Speaking"].includes(event.module) && event.evidenceType === "verified";
  }
  function calibration(events = [], module) {
    const selected = events.filter((event) => event.module === module && isCalibrationEvent(event)).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)).slice(0, 8);
    const questionCount = selected.reduce((sum, event) => sum + Number(event.maxScore || 0), 0);
    const ready = selected.length >= 2 && (!['Listening', 'Reading'].includes(module) || questionCount >= 20);
    const direct = selected.filter((event) => Number(event.maxScore) === 9);
    let score = null;
    if (ready && direct.length) { const weighted = direct.reduce((total, event, index) => ({ sum: total.sum + Number(event.score) * (direct.length - index), weight: total.weight + direct.length - index }), { sum: 0, weight: 0 }); score = roundBand(weighted.sum / weighted.weight); }
    else if (ready) score = accuracyToBand(selected.reduce((sum, event) => sum + Number(event.score) / Number(event.maxScore), 0) / selected.length);
    return { events: selected, required: 2, questionCount, ready, score };
  }
  const finiteScore = (value) => value !== null && value !== "" && Number.isFinite(Number(value));
  const explicitAverage = (scores) => { const values = MODULES.map((module) => scores?.[module]); return values.every(finiteScore) ? roundBand(values.reduce((sum, value) => sum + Number(value), 0) / 4) : null; };
  function learningSignals(events = [], baselineScores = {}) {
    const modules = MODULES.map((module) => ({ module, ...calibration(events, module) }));
    const scores = Object.fromEntries(modules.map((item) => [item.module, item.ready ? item.score : finiteScore(baselineScores[item.module]) ? Number(baselineScores[item.module]) : 5]));
    const ready = modules.filter((item) => item.ready);
    return { modules, scores, readyModules: ready.length, band: ready.length ? roundBand(ready.reduce((sum, item) => sum + item.score, 0) / ready.length) : null };
  }
  const eventBand = (event) => !isCalibrationEvent(event) ? null : Number(event.maxScore) === 9 ? Number(event.score) : accuracyToBand(Number(event.score) / Number(event.maxScore));
  function queueCounts({ words = [], fresh = [], progress = {}, today }) {
    const freshSet = new Set(fresh);
    const pendingWords = words.filter((word) => progress[word]?.reviewDate !== today || progress[word]?.learningState === "relearning");
    const pendingFresh = pendingWords.filter((word) => freshSet.has(word)).length;
    const pendingReview = pendingWords.length - pendingFresh;
    return { fresh: fresh.length, review: words.length - fresh.length, total: words.length, pendingFresh, pendingReview, pending: pendingWords.length, complete: words.length > 0 && pendingWords.length === 0 };
  }
  function promoteFocus(ranked = [], preferred) {
    const result = [...new Set(ranked.filter(Boolean))].slice(0, 3);
    if (result.length >= 3 && MODULES.includes(preferred) && !result.includes(preferred)) result[2] = preferred;
    return result;
  }

  return { WORD_INTERVALS, addDays, normalizeDaily, normalizeProgress, beginAppearance, recordFailure, recordSuccess, buildDailyQueue, projectionDays, migrateStreak, advanceStreak, explicitAverage, isCalibrationEvent, calibration, learningSignals, eventBand, queueCounts, promoteFocus };
});
