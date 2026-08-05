const screens = [...document.querySelectorAll(".screen")];
const navButtons = [...document.querySelectorAll("[data-go]")];
const bottomNav = [...document.querySelectorAll(".bottom-nav button")];
const saveStatus = document.querySelector("#saveStatus");
const toastTargets = [...document.querySelectorAll("[data-toast-target]")];
const sheets = [...document.querySelectorAll("[data-sheet]")];
let feedbackTimer;

const BOTTOM_NAV_PARENT = {
  plan: "today", newsReading: "today",
  word: "practice", dailyWords: "practice", detail: "practice", vocab: "practice",
  listening: "practice", listeningVocab: "practice", reading: "practice", writing: "practice", speaking: "practice",
  settings: "profile", assessment: "profile", later: "practice", timeline: "profile",
};

const SAVED_WORDS_KEY = "ielts-os.savedWords.v1";
const USER_WRONG_QUESTIONS_KEY = "ielts-os.wrongQuestions.v1";
const ATTEMPTS_KEY = "ielts-os.attempts.v1";
const WORD_PROGRESS_KEY = "ielts-os.wordProgress.v1";
const WRITING_DRAFTS_KEY = "ielts-os.writingDrafts.v1";
const SPEAKING_DB = "ielts-os.speaking.v1";
const LAST_SCREEN_KEY = "ielts-os.lastScreen.v1";
const LEARNING_EVENTS_KEY = "ielts-os.learningEvents.v1";
const SPEAKING_SESSIONS_KEY = "ielts-os.speakingSessions.v1";
const AI_MEMORY_KEY = "ielts-os.aiMemory.v1";
const STREAK_KEY = "ielts-os.streak.v1";
const DAILY_NEWS_CACHE_KEY = "ielts-os.dailyNews.v1";
const SAVED_SENTENCES_KEY = "ielts-os.savedSentences.v1";
const AI_ENDPOINT_KEY = "ielts-os.aiEndpoint.v1";
const AI_VERIFIED_ENDPOINT_KEY = "ielts-os.aiVerifiedEndpoint.v1";
const AI_PROVIDER_KEY = "ielts-os.aiProvider.v1";
const ERROR_LOG_KEY = "ielts-os.errorLog.v1";
const PREIMPORT_BACKUP_KEY = "ielts-os.preImportBackup.v1";
const BACKUP_RECOVERY_MARKER_KEY = "ielts-os.backupRecovery.v1";
const ASSESSMENT_SESSION_KEY = "ielts-os.assessmentSession.v1";
const DAILY_PLAN_KEY = "ielts-os.dailyPlan.v1";
const PLAN_ADJUSTMENTS_KEY = "ielts-os.planAdjustments.v1";
const PLAN_MODULES_KEY = "ielts-os.planModules.v1";
const USER_PROFILE_KEY = "ielts-os.userProfile.v1";
const BASELINE_RESULT_KEY = "ielts-os.baselineResult.v1";
const RECOVERY_KEY = "ielts-os.recovery.v1";
const PRACTICE_FAVORITES_KEY = "ielts-os.practiceFavorites.v1";
const LATER_ITEMS_KEY = "ielts-os.laterItems.v1";
const DAILY_WORD_QUEUE_KEY = "ielts-os.dailyWordQueue.v1";
const RESUME_STATE_KEY = "ielts-os.resumeState.v1";
const REMINDER_TIME_KEY = "ielts-os.reminderTime.v1";
const EXAM_MODE_KEY = "ielts-os.examMode.v1";
const DAILY_REFLECTIONS_KEY = "ielts-os.dailyReflections.v1";
const STUDY_PATH_PROGRESS_KEY = "ielts-os.studyPathProgress.v1";
const RECENT_RESOURCES_KEY = "ielts-os.recentResources.v1";
const RESOURCE_PROGRESS_KEY = "ielts-os.resourceProgress.v1";
const LISTENING_AUX_MEDIA_KEY = "ielts-os.listeningAuxMedia.v1";
const LISTENING_MANUAL_MAP_KEY = "ielts-os.listeningManualMap.v1";
const READING_SOURCE_MAP_KEY = "ielts-os.readingSourceMap.v1";
const WRITING_SOURCE_MAP_KEY = "ielts-os.writingSourceMap.v1";
const SPEAKING_SOURCE_MAP_KEY = "ielts-os.speakingSourceMap.v1";
const MEDIA_DOWNLOADS_KEY = "ielts-os.mediaDownloads.v1";
const MEDIA_CACHE_NAME = "ielts-os-media-v1";
const OFFLINE_MEDIA_LIMIT_BYTES = 250 * 1024 * 1024;
const OFFLINE_MEDIA_MAX_AGE_DAYS = 14;

const IELTSReliability = window.IELTSReliability;
if (!IELTSReliability) throw new Error("app-reliability.js must load before app.js");
const IELTSLearning = window.IELTSLearning;
if (!IELTSLearning) throw new Error("learning-core.js must load before app.js");
const wordSessionId = Date.now().toString(36);
let wordAppearanceSerial = 0;
let volatileWordQueue = null;

function markPersistResult(ok) {
  return ok;
}

function persistValue(key, value) {
  return markPersistResult(IELTSReliability.writeValue(localStorage, key, value));
}

function removePersistedValue(key) {
  return markPersistResult(IELTSReliability.removeValue(localStorage, key));
}

function reportPersistResult(ok, successCopy, failureCopy, selector = null) {
  const message = ok ? successCopy : failureCopy;
  if (selector) setText(selector, message);
  else showToast(message, ok ? "success" : "error");
  return ok;
}

const state = {
  wordbook: null,
  practice: null,
  listening: null,
  writing: null,
  tests: null,
  contentManifest: null,
  contentRoadmap: null,
  audioMap: null,
  libraryCatalog: null,
  studyPaths: null,
  studyPathProgress: {},
  resourceProgress: {},
  listeningAuxMedia: {},
  listeningManualMap: {},
  readingSourceMap: {},
  writingSourceMap: {},
  speakingSourceMap: {},
  activeStudyPathId: null,
  studyPathIncompleteOnly: false,
  wrongQuestions: null,
  reading: null,
  currentWordIndex: 0,
  definitionVisible: false,
  translationVisible: false,
  readingAnswers: {},
  readingReviewVisible: false,
  readingMode: "article",
  readingStartedAt: null,
  readingElapsedSeconds: 0,
  readingTimerId: null,
  readingFocusParagraphId: null,
  readingFocusQuestionId: null,
  readingBreakdownParagraphId: null,
  examMode: false,
  listeningPlaying: false,
  listeningTranscriptVisible: false,
  listeningTranslationVisible: false,
  listeningSentenceIndex: 0,
  listeningSentenceLoop: false,
  listeningSentenceRate: 0.88,
  listeningMode: "study",
  listeningVocabScene: "全部",
  listeningVocabSearch: "",
  listeningVocabIndex: 0,
  listeningVocabResult: null,
  activePracticeId: "reading-demo-p1",
  lookupWord: null,
  lookupSourceSentence: "",
  lookupDictionary: "shanbay",
  savedWords: [],
  userWrongQuestions: [],
  attempts: {},
  wordProgress: {},
  wordAppearance: null,
  wordQuiz: { mode: "listen", questions: [], index: 0, correct: 0, locked: false, wrong: [] },
  wordFilter: "全部",
  wordLibrarySearch: "",
  wordLibraryLimit: 80,
  practiceTab: "听力",
  practiceSearch: "",
  practiceDifficulty: "全部",
  practiceStatus: "全部",
  practiceBook: "全部",
  practiceTest: "全部",
  practiceWrongOnly: false,
  practiceResourceFormat: "全部",
  practiceResourceAvailability: "全部",
  libraryLimit: 40,
  recentResources: [],
  practiceFavorites: [],
  laterItems: [],
  writingDrafts: {},
  activeWritingTaskId: null,
  writingTimerId: null,
  writingStartedAt: null,
  writingElapsedSeconds: 0,
  writingMode: "write",
  speakingRecordings: [],
  speakingRecorder: null,
  speakingStream: null,
  speakingStartedAt: null,
  speakingTimerId: null,
  speakingUrls: [],
  speakingRecognition: null,
  speakingNativeTranscribe: false,
  speakingTranscript: "",
  speakingPressActive: false,
  speakingCardIndex: 0,
  speakingMode: "conversation",
  speakingPrepSeconds: 0,
  speakingPrepTimerId: null,
  speakingCompareIds: [],
  speakingSessions: [],
  aiMemory: { dialogueSessions: [], speakingDebriefs: [], moduleReviews: [], agentHistory: [] },
  speakingRecordingsLoaded: false,
  activeSpeakingSessionId: null,
  learningEvents: [],
  wrongModuleFilter: "全部",
  wrongTypeFilter: "全部",
  wrongQuestionTypeFilter: "全部",
  activeWrongId: null,
  wrongMode: "today",
  streak: null,
  dailyNews: [],
  activeNewsIndex: 0,
  newsReadingStartedAt: null,
  newsReadingTimerId: null,
  newsAnswer: "",
  savedSentences: [],
  assessmentSession: null,
  dailyPlanBudget: 60,
  planAdjustments: {},
  planModules: {},
  userProfile: null,
  examWeek: { checklist: {}, reflection: "", reflectionSavedAt: null },
  dailyReflections: {},
  onboardingBudget: 60,
  baselineResult: null,
  synonyms: null,
  dashboardRangeDays: 7,
  timelineDays: 7,
  resumeState: { scrolls: {}, audioTimes: {} },
  startupStatus: "loading",
  startupMissing: [],
  startupError: "",
};

function setStartupStatus(status, message = "正在读取本机学习记录与练习内容。") {
  state.startupStatus = status;
  state.startupError = status === "error" ? message : "";
  const phone = document.querySelector(".phone");
  const startup = document.querySelector("[data-app-startup]");
  const nav = document.querySelector(".bottom-nav");
  IELTSReliability.applyStartupDomState({ status, phone, overlay: startup, nav, screens });
  setText("[data-startup-title]", status === "error" ? "学习内容未能完整打开" : "正在准备今天的学习");
  setText("[data-startup-message]", message);
  document.querySelector("[data-startup-loading]")?.toggleAttribute("hidden", status !== "loading");
  document.querySelector("[data-startup-error]")?.toggleAttribute("hidden", status !== "error");
}

function showScreen(name, restorePosition = false) {
  if (state.startupStatus !== "ready") return false;
  if (name === "detail" && !document.querySelector(".screen[data-screen='detail']")?.classList.contains("active")) state.wordAppearance = null;
  persistResumeState();
  closeSheets();
  document.querySelector(".phone")?.classList.toggle("setup-mode", name === "onboarding" || name === "baseline");

  if (name !== "listening" && state.listeningSentenceLoop) {
    state.listeningSentenceLoop = false;
    window.speechSynthesis?.cancel();
  }
  if (name !== "reading" && state.readingTimerId) {
    clearInterval(state.readingTimerId);
    state.readingTimerId = null;
  }
  if (name !== "speaking" && state.speakingPrepTimerId) {
    clearInterval(state.speakingPrepTimerId);
    state.speakingPrepTimerId = null;
  }

  if (name !== "newsReading" && state.newsReadingTimerId) {
    clearInterval(state.newsReadingTimerId);
    state.newsReadingTimerId = null;
  }
  if (name !== "ai" && aiChat.active) endAiVoiceChat();

  if (name === "profile") renderProfileDashboard();
  if (name === "settings") renderProfileDashboard();
  if (name === "assessment") renderAssessment();
  if (name === "ai") renderAIAssistant();
  if (name === "onboarding") renderOnboarding();
  if (name === "baseline") renderBaseline();
  if (name === "plan") renderStudyPlan();
  if (name === "word") renderWordBook();
  if (name === "wordLibrary") renderWordLibrary();
  if (name === "later") renderLater();
  if (name === "timeline") renderLearningTimeline();
  if (name === "dailyWords") renderDailyWords();
  if (name === "detail") renderWordDetail();
  if (name === "practice") renderPractice();
  if (name === "listening") renderListening();
  if (name === "writing") renderWriting();
  if (name === "reading") renderReading();
  if (name === "vocab") renderVocabBook();
  if (name === "speaking") {
    renderSpeakingCoach();
    ensureSpeakingRecordings();
  }
  if (name === "graph") renderWrongQuestions();
  if (name === "listeningVocab") renderListeningVocabulary();

  if (!["today", "plan", "profile", "settings", "onboarding", "baseline"].includes(name)) persistValue(LAST_SCREEN_KEY, name);

  screens.forEach((screen) => {
    screen.classList.toggle("active", screen.dataset.screen === name);
    if (screen.dataset.screen === name) screen.scrollTop = restorePosition ? Number(state.resumeState.scrolls?.[name] || 0) : 0;
  });
  window.scrollTo(0, 0);

  bottomNav.forEach((button) => {
    button.classList.toggle("active", button.dataset.go === (BOTTOM_NAV_PARENT[name] || name));
  });
  return true;
}

function showToast(message, tone = "info") {
  toastTargets.forEach((target) => {
    const screen = target.closest(".screen");
    if (screen?.classList.contains("active")) target.textContent = message;
  });
  const feedback = document.querySelector("[data-app-feedback]");
  if (!feedback) return;
  feedback.textContent = message;
  feedback.dataset.tone = tone;
  feedback.hidden = false;
  clearTimeout(feedbackTimer);
  feedbackTimer = setTimeout(() => { feedback.hidden = true; }, 3200);
}

function setButtonBusy(button, busy, label = "处理中…") {
  if (!button) return;
  if (busy) button.dataset.idleLabel = button.textContent;
  button.disabled = busy;
  button.textContent = busy ? label : button.dataset.idleLabel || button.textContent;
}

function closeSheets() {
  sheets.forEach((sheet) => {
    sheet.classList.remove("is-open");
    sheet.setAttribute("aria-hidden", "true");
    sheet.setAttribute("inert", "");
  });
}

function openSheet(name) {
  closeSheets();
  const sheet = document.querySelector(`[data-sheet="${name}"]`);
  if (!sheet) return;
  sheet.classList.add("is-open");
  sheet.setAttribute("aria-hidden", "false");
  sheet.removeAttribute("inert");
}

function bindEdgeSwipeBack() {
  const phone = document.querySelector(".phone");
  if (!phone) return;
  let start = null;
  phone.addEventListener("touchstart", (event) => {
    const touch = event.touches[0];
    const interactive = event.target.closest("input, textarea, select, [contenteditable]");
    start = event.touches.length === 1 && touch.clientX <= 28 && !interactive ? { x: touch.clientX, y: touch.clientY } : null;
  }, { passive: true });
  phone.addEventListener("touchend", (event) => {
    if (!start) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = Math.abs(touch.clientY - start.y);
    start = null;
    if (dx < 64 || dx < dy * 1.4) return;
    if (document.querySelector("[data-sheet].is-open")) return closeSheets();
    document.querySelector('.screen.active [aria-label^="返回"]')?.click();
  }, { passive: true });
  phone.addEventListener("touchcancel", () => { start = null; }, { passive: true });
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node && value !== undefined && value !== null) node.textContent = value;
}

function renderDailyReading(items, status = "今日更新") {
  const list = document.querySelector("[data-daily-reading-list]");
  if (!list) return;
  list.replaceChildren();
  setText("[data-daily-reading-status]", status);

  if (!items.length) {
    const note = document.createElement("p");
    note.className = "daily-reading-empty";
    note.textContent = "暂时无法获取英文新闻，请稍后再试。";
    list.append(note);
    return;
  }

  state.dailyNews = items;
  items.slice(0, 2).forEach((item, index) => {
    const link = document.createElement("button");
    link.type = "button";

    const meta = document.createElement("span");
    meta.textContent = `${item.topic} · ${item.date}`;
    const title = document.createElement("strong");
    title.textContent = item.title;
    const summary = document.createElement("p");
    summary.textContent = item.summary;
    link.append(meta, title, summary);
    link.addEventListener("click", () => {
      state.activeNewsIndex = index;
      state.newsAnswer = "";
      renderNewsReading();
      showScreen("newsReading");
    });
    list.append(link);
  });
}

function newsKeywords(item) {
  const stopWords = new Set(["about", "after", "again", "could", "from", "have", "into", "more", "over", "than", "that", "their", "these", "they", "this", "with", "would"]);
  return [...new Set(`${item.title} ${item.summary}`.toLowerCase().match(/[a-z]{5,}/g) || [])]
    .filter((word) => !stopWords.has(word))
    .slice(0, 5);
}

function newsDifficulty(item) {
  const words = `${item.title} ${item.summary}`.match(/[a-z]+/gi) || [];
  const average = words.reduce((sum, word) => sum + word.length, 0) / Math.max(1, words.length);
  return average >= 6.2 ? "C1" : average >= 5.2 ? "B2" : "B1";
}

function renderNewsReading() {
  const item = state.dailyNews[state.activeNewsIndex];
  if (!item) return;
  if (state.newsReadingTimerId) clearInterval(state.newsReadingTimerId);
  state.newsReadingTimerId = null;
  state.newsReadingStartedAt = null;
  const keywords = newsKeywords(item);
  setText("[data-news-meta]", `${item.topic.toUpperCase()} · ${newsDifficulty(item)}`);
  setText("[data-news-title]", item.title);
  setText("[data-news-summary]", "阅读标题与摘要，先判断主题，再完成英文概括。");
  setText("[data-news-excerpt]", item.summary);
  const source = document.querySelector("[data-news-source]");
  if (source) source.href = item.url;

  const keywordList = document.querySelector("[data-news-keywords]");
  keywordList?.replaceChildren(...keywords.map((word) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = word;
    button.addEventListener("click", () => openWordLookup(word, item.summary));
    return button;
  }));

  const options = document.querySelector("[data-news-options]");
  const topics = [...new Set([item.topic, "Culture", "Sport"])];
  options?.replaceChildren(...topics.map((topic) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = topic;
    button.addEventListener("click", () => {
      state.newsAnswer = topic;
      options.querySelectorAll("button").forEach((option) => option.classList.toggle("selected", option === button));
    });
    return button;
  }));
  setText("[data-news-time]", "00:00");
  setText("[data-news-result]", "完成理解题和英文摘要后，将记录到学习分析。");
  const summary = document.querySelector("[data-news-user-summary]");
  if (summary) summary.value = "";
}

function toggleNewsTimer() {
  const button = document.querySelector("[data-news-timer]");
  if (state.newsReadingTimerId) {
    clearInterval(state.newsReadingTimerId);
    state.newsReadingTimerId = null;
    if (button) button.textContent = "继续";
    return;
  }
  state.newsReadingStartedAt ||= Date.now();
  if (button) button.textContent = "暂停";
  state.newsReadingTimerId = setInterval(() => {
    const seconds = Math.floor((Date.now() - state.newsReadingStartedAt) / 1000);
    setText("[data-news-time]", speakingDuration(seconds));
  }, 1000);
}

async function submitNewsReading() {
  const item = state.dailyNews[state.activeNewsIndex];
  const summary = document.querySelector("[data-news-user-summary]")?.value.trim() || "";
  const wordCount = summary.split(/\s+/).filter(Boolean).length;
  if (!state.newsAnswer || wordCount < 20) {
    setText("[data-news-result]", "请先选择文章主题，并写至少 20 个英文单词。");
    return;
  }
  const correct = state.newsAnswer === item.topic;
  const keyTerms = newsKeywords(item).slice(0, 3);
  const coverage = keyTerms.filter((word) => summary.toLowerCase().includes(word)).length;
  const minutes = Math.max(1, Math.round((Date.now() - (state.newsReadingStartedAt || Date.now())) / 60000));
  trackLearningEvent({ module: "Reading", activity: "每日新闻精读", durationMinutes: minutes, score: (correct ? 1 : 0) + (coverage >= 2 ? 1 : 0), maxScore: 2, sourceId: item.url });
  if (!correct) addWrongQuestion({
    id: `news-${item.url}`,
    module: "Reading",
    title: "新闻主旨判断",
    sourceMaterial: item.title,
    userAnswer: state.newsAnswer,
    correctAnswer: item.topic,
    evidence: item.summary,
    mistakeType: "reading-logic",
    aiExplanation: `文章来自 ${item.topic} 栏目，标题和摘要共同指向该主题。`,
    reviewPoints: ["先识别标题核心名词", "再用摘要确认文章主旨"],
    nextReviewDate: tomorrowIsoDate(),
    createdAt: new Date().toISOString(),
    status: "待复盘",
  });
  if (state.newsReadingTimerId) clearInterval(state.newsReadingTimerId);
  state.newsReadingTimerId = null;
  state.newsReadingStartedAt = null;
  const summaryNote = coverage >= 2 ? "摘要覆盖了核心信息" : `摘要可补充关键词：${keyTerms.join(" / ")}`;
  setText("[data-news-result]", correct ? `精读完成：主题判断正确；${summaryNote}。` : `已加入错题复盘；正确主题是 ${item.topic}，${summaryNote}。`);
  try {
    const aiText = await requestAI("news_feedback", { article: { title: item.title, topic: item.topic, summary: item.summary }, learnerSummary: summary });
    if (aiText) setText("[data-news-result]", aiText);
  } catch (error) {}
}

function saveNewsSentence() {
  const item = state.dailyNews[state.activeNewsIndex];
  if (!item) return;
  const saved = { id: item.url, text: item.summary, source: item.title, url: item.url, savedAt: new Date().toISOString() };
  const existing = state.savedSentences.findIndex((sentence) => sentence.id === saved.id);
  const previous = [...state.savedSentences];
  if (existing >= 0) state.savedSentences[existing] = saved;
  else state.savedSentences.unshift(saved);
  if (!persistValue(SAVED_SENTENCES_KEY, JSON.stringify(state.savedSentences))) {
    state.savedSentences = previous;
    return setText("[data-news-result]", "收藏失败，请释放存储空间后重试。");
  }
  setText("[data-news-result]", "本段已收藏，并会进入后续复述与写作素材练习。");
}

const BACKUP_KEYS = [SAVED_WORDS_KEY, USER_WRONG_QUESTIONS_KEY, ATTEMPTS_KEY, WORD_PROGRESS_KEY, WRITING_DRAFTS_KEY, LAST_SCREEN_KEY, LEARNING_EVENTS_KEY, SPEAKING_SESSIONS_KEY, AI_MEMORY_KEY, STREAK_KEY, DAILY_NEWS_CACHE_KEY, SAVED_SENTENCES_KEY, ERROR_LOG_KEY, ASSESSMENT_SESSION_KEY, DAILY_PLAN_KEY, PLAN_ADJUSTMENTS_KEY, PLAN_MODULES_KEY, USER_PROFILE_KEY, BASELINE_RESULT_KEY, PRACTICE_FAVORITES_KEY, LATER_ITEMS_KEY, RECENT_RESOURCES_KEY, RESOURCE_PROGRESS_KEY, LISTENING_AUX_MEDIA_KEY, LISTENING_MANUAL_MAP_KEY, READING_SOURCE_MAP_KEY, WRITING_SOURCE_MAP_KEY, SPEAKING_SOURCE_MAP_KEY, DAILY_WORD_QUEUE_KEY, RESUME_STATE_KEY, REMINDER_TIME_KEY, EXAM_MODE_KEY, DAILY_REFLECTIONS_KEY, STUDY_PATH_PROGRESS_KEY];

function recordClientError(message, source = "app") {
  const logs = loadStoredArray(ERROR_LOG_KEY);
  logs.unshift({ message: String(message).slice(0, 500), source, createdAt: new Date().toISOString() });
  try {
    localStorage.setItem(ERROR_LOG_KEY, JSON.stringify(logs.slice(0, 50)));
  } catch (_) {}
}

window.addEventListener("error", (event) => recordClientError(event.message, event.filename || "window"));
window.addEventListener("unhandledrejection", (event) => recordClientError(event.reason?.message || event.reason, "promise"));

function persistSessionState() {
  const task = activeWritingTask();
  if (task) {
    const draft = writingDraft(task.id);
    draft.elapsedSeconds = state.writingElapsedSeconds;
    if (draft.text || draft.notes) draft.updatedAt ||= new Date().toISOString();
    persistWritingDrafts();
  }
  persistAttempts();
  persistWordProgress();
  persistUserWrongQuestions();
  persistLearningEvents();
  persistSpeakingSessions();
  persistResumeState();
}

function persistResumeState() {
  const activeScreen = document.querySelector(".screen.active");
  if (activeScreen) state.resumeState.scrolls[activeScreen.dataset.screen] = activeScreen.scrollTop;
  const audio = document.querySelector("[data-native-audio-player] audio");
  if (audio && state.activePracticeId) state.resumeState.audioTimes[state.activePracticeId] = audio.currentTime || 0;
  Object.assign(state.resumeState, {
    activePracticeId: state.activePracticeId,
    currentWordIndex: state.currentWordIndex,
    readingElapsedSeconds: state.readingElapsedSeconds,
    listeningSentenceIndex: state.listeningSentenceIndex,
    listeningMode: state.listeningMode,
    writingMode: state.writingMode,
    speakingMode: state.speakingMode,
    wrongMode: state.wrongMode,
    readingMode: state.readingMode,
    listeningVocabScene: state.listeningVocabScene,
    listeningVocabIndex: state.listeningVocabIndex,
  });
  persistValue(RESUME_STATE_KEY, JSON.stringify(state.resumeState));
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") persistSessionState();
});
window.addEventListener("pagehide", persistSessionState);

function configuredAIEndpoint() {
  return localStorage.getItem(AI_ENDPOINT_KEY)?.replace(/\/$/, "") || "";
}

function aiServiceReady() {
  const endpoint = configuredAIEndpoint();
  return Boolean(endpoint && localStorage.getItem(AI_VERIFIED_ENDPOINT_KEY) === endpoint);
}

async function requestAI(task, payload) {
  const endpoint = configuredAIEndpoint();
  if (!aiServiceReady()) return null;
  const response = await fetch(`${endpoint}/api/ai`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, payload: { ...payload, learnerContext: learningMemorySnapshot() } }),
  });
  if (!response.ok) throw new Error(`AI request failed: ${response.status}`);
  const result = await response.json();
  return String(result.text || "").trim() || null;
}

async function saveStudyReminder() {
  const plugin = window.Capacitor?.Plugins?.LocalNotifications;
  if (!plugin) return setText("[data-reminder-status]", "请在 iPhone App 中启用提醒。");
  const [hour, minute] = (document.querySelector("[data-reminder-time]")?.value || "20:30").split(":").map(Number);
  const permission = await plugin.requestPermissions();
  if (permission.display !== "granted") return setText("[data-reminder-status]", "通知权限未开启，请前往系统设置允许。");
  const at = new Date();
  at.setHours(hour, minute, 0, 0);
  if (at <= new Date()) at.setDate(at.getDate() + 1);
  await plugin.cancel({ notifications: [{ id: 101 }] });
  await plugin.schedule({ notifications: [{ id: 101, title: "IELTS OS · 今日学习", body: "完成今天最优先的一项任务，保持连续学习。", schedule: { at, repeats: true, every: "day" }, sound: null, attachments: null, actionTypeId: "", extra: { screen: "today" } }] });
  reportPersistResult(persistValue(REMINDER_TIME_KEY, `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`), `已启用：每天 ${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")} 提醒。`, "提醒已启用，但时间未能保存，请释放存储空间后重试。", "[data-reminder-status]");
}

async function disableStudyReminder() {
  const plugin = window.Capacitor?.Plugins?.LocalNotifications;
  if (plugin) await plugin.cancel({ notifications: [{ id: 101 }] });
  reportPersistResult(removePersistedValue(REMINDER_TIME_KEY), "学习提醒已关闭。", "提醒已关闭，但本机状态未能保存，请释放存储空间后重试。", "[data-reminder-status]");
}

function exportBackup() {
  let payload;
  try { payload = { version: 1, exportedAt: new Date().toISOString(), data: IELTSReliability.captureValues(localStorage, BACKUP_KEYS) }; }
  catch (_) { return setText("[data-backup-status]", "无法读取本机学习记录，请检查存储权限后重试。"); }
  const ok = IELTSReliability.createBrowserBackup({ payload, filename: `ielts-os-backup-${localIsoDate()}.json`, document, urlApi: URL, BlobCtor: Blob, setTimeoutFn: setTimeout });
  reportPersistResult(ok, "学习记录已导出；口语录音和离线媒体仍保留在本机。", "备份文件未能导出，请稍后重试。", "[data-backup-status]");
}

function renderBackupStatus() {
  const undo = document.querySelector("[data-undo-backup-import]");
  if (undo) undo.hidden = !localStorage.getItem(PREIMPORT_BACKUP_KEY);
}

async function importBackup(file) {
  try {
    const payload = JSON.parse(await file.text());
    if (payload.version !== 1 || !payload.data || typeof payload.data !== "object") throw new Error("invalid backup");
    const targetKeys = BACKUP_KEYS.filter((key) => typeof payload.data[key] === "string");
    const snapshot = {
      savedAt: new Date().toISOString(),
      data: IELTSReliability.captureValues(localStorage, targetKeys),
    };
    if (!persistValue(PREIMPORT_BACKUP_KEY, JSON.stringify(snapshot))) {
      setText("[data-backup-status]", "无法创建导入前快照");
      return;
    }
    const changes = Object.fromEntries(targetKeys.map((key) => [key, IELTSReliability.mergeBackupValue(localStorage.getItem(key), payload.data[key])]));
    const result = IELTSReliability.applyChanges(localStorage, changes);
    if (!result.ok) {
      if (result.compensationFailedKeys.length) {
        const markerSaved = persistValue(BACKUP_RECOVERY_MARKER_KEY, JSON.stringify({ operation: "import", failedKeys: result.compensationFailedKeys, createdAt: new Date().toISOString() }));
        setText("[data-backup-status]", markerSaved ? "数据恢复不完整；导入前快照已保留，请释放存储空间后点击撤销导入。" : "数据恢复不完整且恢复标记未保存；导入前快照仍保留，请释放存储空间后点击撤销导入。");
      } else {
        removePersistedValue(PREIMPORT_BACKUP_KEY);
        removePersistedValue(BACKUP_RECOVERY_MARKER_KEY);
        setText("[data-backup-status]", "导入写入失败，当前数据已恢复且未合并。");
      }
      renderBackupStatus();
      return;
    }
    removePersistedValue(BACKUP_RECOVERY_MARKER_KEY);
    renderBackupStatus();
    setText("[data-backup-status]", `已合并 ${targetKeys.length} 项学习数据；导入前快照已保留，重新打开应用后生效。`);
  } catch (error) {
    setText("[data-backup-status]", /storage read failed/.test(error.message) ? "无法读取本机学习记录，未执行导入。" : "备份文件无效，未修改当前数据。");
  }
}

function undoBackupImport() {
  try {
    const snapshot = JSON.parse(localStorage.getItem(PREIMPORT_BACKUP_KEY) || "");
    if (!snapshot?.data || typeof snapshot.data !== "object") throw new Error("missing snapshot");
    const changes = Object.fromEntries(Object.entries(snapshot.data).map(([key, value]) => [key, value ?? null]));
    const result = IELTSReliability.applyChanges(localStorage, changes);
    if (!result.ok) {
      if (result.compensationFailedKeys.length) persistValue(BACKUP_RECOVERY_MARKER_KEY, JSON.stringify({ operation: "undo", failedKeys: result.compensationFailedKeys, createdAt: new Date().toISOString() }));
      renderBackupStatus();
      setText("[data-backup-status]", result.compensationFailedKeys.length ? "数据恢复不完整；快照已保留，请释放存储空间后再次撤销。" : "暂时无法恢复；当前导入数据未改变，可稍后重试。");
      return;
    }
    const cleared = removePersistedValue(BACKUP_RECOVERY_MARKER_KEY) && removePersistedValue(PREIMPORT_BACKUP_KEY);
    if (!cleared) {
      setText("[data-backup-status]", "数据已恢复，但恢复标记暂未清除；可稍后再次确认。");
      return;
    }
    setText("[data-backup-status]", "已恢复到导入前的数据，正在重新加载…");
    setTimeout(() => window.location.reload(), 250);
  } catch (error) {
    renderBackupStatus();
    setText("[data-backup-status]", /storage read failed/.test(error.message) ? "无法读取恢复快照，请检查存储权限后重试。" : "没有可恢复的导入前快照。");
  }
}

async function loadDailyReading() {
  const cached = loadStoredArray(DAILY_NEWS_CACHE_KEY);
  if (cached.length) renderDailyReading(cached, "最近更新");

  try {
    const url = "https://content.guardianapis.com/search?section=science%7Ctechnology%7Cenvironment&order-by=newest&page-size=4&show-fields=trailText&api-key=test";
    const response = await fetch(url, { signal: AbortSignal.timeout?.(8000) });
    if (!response.ok) throw new Error(`News request failed: ${response.status}`);
    const payload = await response.json();
    const items = (payload.response?.results || []).map((article) => ({
      title: article.webTitle,
      url: article.webUrl,
      topic: article.sectionName || "News",
      date: new Date(article.webPublicationDate).toLocaleDateString("zh-CN", { month: "short", day: "numeric" }),
      summary: String(article.fields?.trailText || "打开原文，结合关键词完成今日精读。").replace(/<[^>]*>/g, ""),
    }));
    persistValue(DAILY_NEWS_CACHE_KEY, JSON.stringify(items));
    renderDailyReading(items);
  } catch (error) {
    if (!cached.length) renderDailyReading([], "离线");
    console.warn("Daily reading unavailable", error);
  }
}

function loadSavedWords() {
  return loadStoredJson(SAVED_WORDS_KEY, [], Array.isArray);
}

function persistSavedWords() {
  return persistValue(SAVED_WORDS_KEY, JSON.stringify(state.savedWords));
}

function loadUserWrongQuestions() {
  return loadStoredJson(USER_WRONG_QUESTIONS_KEY, [], Array.isArray);
}

function persistUserWrongQuestions() {
  return persistValue(USER_WRONG_QUESTIONS_KEY, JSON.stringify(state.userWrongQuestions));
}

function loadAttempts() {
  return loadStoredJson(ATTEMPTS_KEY, {}, (value) => value && typeof value === "object" && !Array.isArray(value));
}

function persistAttempts() {
  return persistValue(ATTEMPTS_KEY, JSON.stringify(state.attempts));
}

function loadWordProgress() {
  return loadStoredJson(WORD_PROGRESS_KEY, {}, (value) => value && typeof value === "object" && !Array.isArray(value));
}

function persistWordProgress() {
  return persistValue(WORD_PROGRESS_KEY, JSON.stringify(state.wordProgress));
}

function loadWritingDrafts() {
  return loadStoredJson(WRITING_DRAFTS_KEY, {}, (value) => value && typeof value === "object" && !Array.isArray(value));
}

function persistWritingDrafts() {
  return persistValue(WRITING_DRAFTS_KEY, JSON.stringify(state.writingDrafts));
}

function loadStoredArray(key) {
  return loadStoredJson(key, [], Array.isArray);
}

function loadStoredJson(key, fallback, isValid) {
  let raw;
  try {
    raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const value = JSON.parse(raw);
    if (!isValid(value)) throw new Error("unexpected storage shape");
    return value;
  } catch (error) {
    if (key !== RECOVERY_KEY && typeof raw === "string") {
      let recoveries = [];
      try {
        const existing = JSON.parse(localStorage.getItem(RECOVERY_KEY) || "[]");
        recoveries = Array.isArray(existing) ? existing : existing && typeof existing === "object" ? [existing] : [];
      } catch (recoveryError) {
        console.warn("Recovery index was corrupt", recoveryError);
      }
      recoveries.unshift({ key, raw: raw.slice(0, 100000), recoveredAt: new Date().toISOString() });
      try {
        localStorage.setItem(RECOVERY_KEY, JSON.stringify(recoveries.slice(0, 5)));
      } catch (_) {}
    }
    removePersistedValue(key);
    console.warn(`Recovered corrupt storage: ${key}`, error);
    return fallback;
  }
}

function persistLearningEvents() {
  return persistValue(LEARNING_EVENTS_KEY, JSON.stringify(state.learningEvents));
}

function migrateLegacySampleState() {
  if (!state.attempts["reading-demo-p1"]?.submitted) {
    const filtered = state.userWrongQuestions.filter((item) => item.id !== "reading-demo-p1-q4");
    if (filtered.length !== state.userWrongQuestions.length) {
      state.userWrongQuestions = filtered;
      persistUserWrongQuestions();
    }
  }
  const migrated = IELTSLearning.migrateStreak(state.streak, state.learningEvents.map((event) => ({ ...event, date: localDateOf(event.createdAt) })), localIsoDate());
  if (!migrated) {
    state.streak = null;
    removePersistedValue(STREAK_KEY);
  } else if (JSON.stringify(state.streak) !== JSON.stringify(migrated)) {
    state.streak = migrated;
    persistValue(STREAK_KEY, JSON.stringify(state.streak));
  }
}

function trackLearningEvent({ module, activity, durationMinutes = 1, score = null, maxScore = null, sourceId = "", evidenceType = "practice" }) {
  const duplicate = state.learningEvents.find((event) => event.module === module && event.activity === activity && event.sourceId === sourceId && Date.now() - new Date(event.createdAt).getTime() < 10000);
  if (duplicate) return duplicate;
  const previous = state.learningEvents;
  const event = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    module,
    activity,
    durationMinutes: Math.max(1, Math.round(durationMinutes)),
    score,
    maxScore,
    sourceId,
    evidenceType,
    createdAt: new Date().toISOString(),
  };
  state.learningEvents = [event, ...previous].slice(0, 1000);
  if (!persistLearningEvents()) {
    state.learningEvents = previous;
    showToast("学习记录未能保存，连续学习天数没有改变；请释放存储空间后重试。", "error");
    return null;
  }
  completeActiveStudyPath(module);
  if (activity !== "首次基线诊断" && durationMinutes > 0) updateLearningStreak();
  refreshLearningSurfaces();
  return event;
}

function refreshLearningSurfaces() {
  renderToday();
  renderStudyPlan();
  renderWrongQuestions();
  renderProfileDashboard();
}

function streakFromLearningEvents() {
  return IELTSLearning.migrateStreak(null, state.learningEvents.map((event) => ({ ...event, date: localDateOf(event.createdAt) })), localIsoDate())?.count || 0;
}

function updateLearningStreak() {
  state.streak = IELTSLearning.advanceStreak(state.streak, localIsoDate());
  persistValue(STREAK_KEY, JSON.stringify(state.streak));
}

function persistSpeakingSessions() {
  return persistValue(SPEAKING_SESSIONS_KEY, JSON.stringify(state.speakingSessions));
}

function persistAiMemory() {
  return persistValue(AI_MEMORY_KEY, JSON.stringify(state.aiMemory));
}

function rememberModuleReview(module, summary, evidence = {}) {
  if (!summary) return null;
  const review = { id: `${module.toLowerCase()}-${Date.now()}`, module, summary: String(summary).slice(0, 4000), evidence, createdAt: new Date().toISOString() };
  state.aiMemory.moduleReviews.unshift(review);
  state.aiMemory.moduleReviews = state.aiMemory.moduleReviews.slice(0, 40);
  persistAiMemory();
  renderModuleCoachReview(module);
  renderSubjectCoaches();
  return review;
}

function latestModuleReview(module) {
  return state.aiMemory.moduleReviews.find((item) => item.module === module) || null;
}

function learningMemorySnapshot() {
  const recentMistakes = state.userWrongQuestions
    .filter((item) => item.status !== "已掌握")
    .slice(0, 12)
    .map((item) => ({ module: item.module, type: item.mistakeType || item.category || "待复盘", title: item.title }));
  const weakCounts = recentMistakes.reduce((counts, item) => {
    counts[item.module] = (counts[item.module] || 0) + 1;
    return counts;
  }, {});
  const latestDebrief = state.aiMemory.speakingDebriefs[0];
  return {
    learner: {
      targetBand: state.userProfile?.targetBand || null,
      examDate: state.userProfile?.examDate || null,
      dailyMinutes: state.userProfile?.dailyMinutes || state.dailyPlanBudget,
    },
    progress: {
      learnedWords: Object.keys(state.wordProgress || {}).length,
      dueReviews: recentMistakes.length,
      speakingSessions: state.aiMemory.dialogueSessions.length + state.speakingSessions.length,
      aiReviews: state.aiMemory.moduleReviews.length,
      weakModules: Object.entries(weakCounts).sort((a, b) => b[1] - a[1]).map(([module, count]) => ({ module, count })),
    },
    speaking: {
      recentSessions: state.aiMemory.dialogueSessions.slice(0, 3),
      latestDebrief: latestDebrief ? { summary: latestDebrief.summary, createdAt: latestDebrief.createdAt } : null,
    },
    moduleReviews: state.aiMemory.moduleReviews.slice(0, 8).map((item) => ({ module: item.module, summary: item.summary.slice(0, 1200), evidence: item.evidence, createdAt: item.createdAt })),
    recentMistakes,
  };
}

function rememberAgentExchange(question, answer) {
  state.aiMemory.agentHistory.unshift({ question, answer: answer.slice(0, 1200), createdAt: new Date().toISOString() });
  state.aiMemory.agentHistory = state.aiMemory.agentHistory.slice(0, 20);
  persistAiMemory();
}

function activeSpeakingSession() {
  let session = state.speakingSessions.find((item) => item.id === state.activeSpeakingSessionId);
  if (session) return session;
  const card = SPEAKING_CARDS[state.speakingCardIndex] || SPEAKING_CARDS[0];
  session = {
    id: `speaking-${Date.now()}`,
    cardIndex: state.speakingCardIndex,
    title: `${card.part} · ${card.title}`,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    turns: [{ role: "coach", text: card.question, createdAt: new Date().toISOString() }],
  };
  state.speakingSessions.unshift(session);
  state.activeSpeakingSessionId = session.id;
  persistSpeakingSessions();
  return session;
}

function activeWritingTask() {
  if (!state.writing?.tasks?.length) return null;
  return state.writing.tasks.find((task) => task.id === state.activeWritingTaskId) || state.writing.tasks[0];
}

function localIsoDate(offsetDays = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function localDateOf(value) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

const MODULE_LABELS = {
  Vocabulary: "词汇",
  Listening: "听力",
  Reading: "阅读",
  Writing: "写作",
  Speaking: "口语",
  Review: "复盘",
};

const WEEKLY_GOALS = { Vocabulary: 60, Listening: 90, Reading: 90, Writing: 80, Speaking: 60, Review: 40 };

function startOfWeek() {
  const date = new Date();
  const day = date.getDay() || 7;
  date.setDate(date.getDate() - day + 1);
  date.setHours(0, 0, 0, 0);
  return date;
}

function weeklyModuleMinutes() {
  const start = startOfWeek();
  return state.learningEvents.reduce((totals, event) => {
    if (new Date(event.createdAt) >= start) totals[event.module] = (totals[event.module] || 0) + Number(event.durationMinutes || 0);
    return totals;
  }, {});
}

function learningStreak() {
  return state.streak?.count || streakFromLearningEvents();
}

function isCalibrationEvent(event) {
  return IELTSLearning.isCalibrationEvent(event);
}

function moduleEvidence(module) {
  return IELTSLearning.calibration(state.learningEvents, module);
}

function moduleBandScores() {
  return IELTSLearning.learningSignals(state.learningEvents, state.baselineResult?.scores).scores;
}

function eventBand(event) {
  return IELTSLearning.eventBand(event);
}

function dashboardSnapshot(days = state.dashboardRangeDays) {
  const rangeDays = days === 30 ? 30 : 7;
  const dates = Array.from({ length: rangeDays }, (_, index) => localIsoDate(index - rangeDays + 1));
  const dateSet = new Set(dates);
  const events = state.learningEvents.filter((event) => dateSet.has(localDateOf(event.createdAt)));
  const daily = dates.map((date) => ({
    date,
    minutes: events.filter((event) => localDateOf(event.createdAt) === date).reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0),
  }));
  const moduleMinutes = Object.keys(WEEKLY_GOALS).reduce((totals, module) => {
    totals[module] = events.filter((event) => event.module === module).reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0);
    return totals;
  }, {});
  const plan = dailyPlan();
  const completed = plan.filter((item) => item.complete).length;
  const movement = ["Listening", "Reading", "Writing", "Speaking"].map((module) => {
    const scored = moduleEvidence(module).events
      .filter((event) => eventBand(event) !== null)
      .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
      .slice(0, 8);
    const recent = scored.slice(0, 4).map(eventBand);
    const previous = scored.slice(4, 8).map(eventBand);
    const average = (values) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    const current = average(recent);
    const prior = average(previous);
    return { module, samples: recent.length, current, delta: current !== null && prior !== null ? current - prior : null };
  });
  const activeDays = daily.filter((day) => day.minutes > 0).length;
  const totalMinutes = daily.reduce((sum, day) => sum + day.minutes, 0);
  const reviewItems = state.userWrongQuestions;
  const latest = events.slice().sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))[0];
  return { rangeDays, daily, moduleMinutes, movement, activeDays, totalMinutes, completed, planTotal: plan.length, dueReviews: wrongReviewQueue(reviewItems).length, latest };
}

function overallBand(scores = moduleBandScores()) {
  return IELTSLearning.explicitAverage(scores);
}

const MODULE_TARGETS = { Listening: "listening", Reading: "reading", Writing: "writing", Speaking: "speaking", Vocabulary: "word", Review: "graph" };

function learningPriorities() {
  const minutes = weeklyModuleMinutes();
  const scores = moduleBandScores();
  const pending = wrongReviewQueue(state.userWrongQuestions).length;
  const laterCounts = state.laterItems.reduce((counts, item) => ({ ...counts, [item.module]: (counts[item.module] || 0) + 1 }), {});
  return Object.keys(WEEKLY_GOALS)
    .map((module) => ({ module, target: MODULE_TARGETS[module], score: scores[module] || 5, estimated: ["Listening", "Reading", "Writing", "Speaking"].includes(module) && (Boolean(state.baselineResult?.scores?.[module]) || moduleEvidence(module).ready), ratio: (minutes[module] || 0) / WEEKLY_GOALS[module], urgency: (module === "Review" ? Math.min(1, pending / 3) : 0) + Math.min(0.75, Number(laterCounts[module] || 0) / 3), laterCount: Number(laterCounts[module] || 0) }))
    .sort((a, b) => (a.ratio - a.urgency) - (b.ratio - b.urgency) || a.score - b.score)
    .slice(0, 3)
    .map((item) => ({ ...item, reason: item.module === "Review" && pending ? `${pending} 项待复盘` : item.laterCount ? `${item.laterCount} 项稍后学` : `完成 ${Math.min(100, Math.round(item.ratio * 100))}%${item.estimated ? ` · 估分 ${item.score.toFixed(1)}` : " · 尚未校准"}` }));
}

const PLAN_TASKS = {
  Vocabulary: "复习到期词并完成今日核心词",
  Listening: "完成一组精听与定位练习",
  Reading: "完成限时阅读并复盘错题",
  Writing: "完成提纲或一段限时写作",
  Speaking: "完成三轮口语回答并回听",
  Review: "清理到期错题与薄弱知识点",
};

function listeningPlanSummary() {
  const counts = state.userWrongQuestions
    .filter((item) => item.module === "Listening" && item.scene && !isWrongMastered(item))
    .reduce((result, item) => ({ ...result, [item.scene]: (result[item.scene] || 0) + 1 }), {});
  const weakScene = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];
  return weakScene ? `优先练习薄弱场景：${weakScene}` : "完成一组场景词听写与精听定位";
}

function moduleWrongFocus(module) {
  const items = state.userWrongQuestions
    .filter((item) => item.module === module && !isWrongMastered(item));
  const counts = items.reduce((result, item) => {
    const type = item.mistakeType || "understanding";
    result[type] = (result[type] || 0) + 1;
    return result;
  }, {});
  const [type, count] = Object.entries(counts).sort((a, b) => b[1] - a[1])[0] || [];
  return type ? `${wrongTypeLabel(type)}（${count} 项）` : "本模块核心能力";
}

function modulePlanSummary(module) {
  if (module === "Vocabulary") return `复习到期词并完成 ${newWordsPerDay()} 个新词`;
  if (module === "Listening") return listeningPlanSummary();
  if (module === "Review") return "清理到期错题与薄弱知识点";
  const focus = moduleWrongFocus(module);
  return `${PLAN_TASKS[module]}；优先解决：${focus}`;
}

const MODULE_COMPLETION_MINUTES = { Listening: 12, Reading: 10, Writing: 10, Speaking: 3, Review: 3 };

function moduleProgressToday(module, plannedMinutes = 0) {
  const events = state.learningEvents.filter((event) => event.module === module
    && event.activity !== "首次基线诊断"
    && localDateOf(event.createdAt) === localIsoDate());
  const actualMinutes = Math.round(events.reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0));
  const activityMinimum = module === "Vocabulary" ? newWordsPerDay() : MODULE_COMPLETION_MINUTES[module] || 5;
  const requiredMinutes = Math.max(1, Math.min(Number(plannedMinutes) || activityMinimum, activityMinimum));
  return { actualMinutes, requiredMinutes, complete: actualMinutes >= requiredMinutes };
}

function dailyPlan(offsetDays = 0) {
  const budget = state.dailyPlanBudget;
  const minutes = [Math.round(budget * 0.4 / 5) * 5, Math.round(budget * 0.35 / 5) * 5];
  minutes.push(budget - minutes[0] - minutes[1]);
  const date = localIsoDate(offsetDays);
  const priorities = learningPriorities();
  const previousReflection = state.dailyReflections[localIsoDate(offsetDays - 1)];
  const ranked = IELTSLearning.promoteFocus(priorities.map((item) => item.module), previousReflection?.focus);
  if (offsetDays === 0 && (!Array.isArray(state.planModules[date]) || state.planModules[date].length !== 3)) {
    state.planModules[date] = ranked;
    persistValue(PLAN_MODULES_KEY, JSON.stringify(state.planModules));
  }
  const modules = offsetDays === 0 ? state.planModules[date] : ranked;
  return modules.map((module, index) => {
    const plannedMinutes = Math.max(5, Number(state.planAdjustments[`${date}:${module}`]) || minutes[index]);
    const progress = offsetDays === 0 ? moduleProgressToday(module, plannedMinutes) : { actualMinutes: 0, requiredMinutes: 0, complete: false };
    return {
      ...(priorities.find((item) => item.module === module) || { module, target: MODULE_TARGETS[module], score: moduleBandScores()[module] || 5, ratio: 0, reason: "今日计划已固定" }),
      minutes: plannedMinutes,
      summary: modulePlanSummary(module),
      ...progress,
    };
  });
}

function renderDailyReflection() {
  const reflection = state.dailyReflections[localIsoDate()] || {};
  document.querySelectorAll("button[data-reflection-blocker]").forEach((button) => button.classList.toggle("selected", button.dataset.reflectionBlocker === reflection.blocker));
  document.querySelectorAll("button[data-reflection-focus]").forEach((button) => button.classList.toggle("selected", button.dataset.reflectionFocus === reflection.focus));
  const note = document.querySelector("[data-reflection-note]");
  if (note && note.value !== (reflection.note || "")) note.value = reflection.note || "";
  setText("[data-reflection-status]", reflection.savedAt ? `已保存 · 明天优先${MODULE_LABELS[reflection.focus] || "学习"}` : "为明天微调计划");
}

function saveDailyReflection() {
  const blocker = document.querySelector("[data-reflection-blocker].selected")?.dataset.reflectionBlocker || "";
  const focus = document.querySelector("[data-reflection-focus].selected")?.dataset.reflectionFocus || "";
  const note = document.querySelector("[data-reflection-note]")?.value.trim() || "";
  if (!blocker || !focus) return showToast("请各选一个：今天的卡点和明天的重点。", "error");
  state.dailyReflections[localIsoDate()] = { blocker, focus, note, savedAt: new Date().toISOString() };
  if (!persistValue(DAILY_REFLECTIONS_KEY, JSON.stringify(state.dailyReflections))) return showToast("复盘未能保存，请释放存储空间后重试。", "error");
  trackLearningEvent({ module: "Review", activity: "每日复盘", durationMinutes: 1, sourceId: localIsoDate() });
  renderStudyPlan();
  renderToday();
  showToast(`已保存：明天会优先安排${MODULE_LABELS[focus]}。`, "success");
}

function adjustPlanMinutes(module, offsetDays, delta) {
  const date = localIsoDate(offsetDays);
  const task = dailyPlan(offsetDays).find((item) => item.module === module);
  if (!task) return;
  state.planAdjustments[`${date}:${module}`] = Math.max(5, task.minutes + delta);
  persistValue(PLAN_ADJUSTMENTS_KEY, JSON.stringify(state.planAdjustments));
  renderStudyPlan();
}

function examPlanMilestone() {
  const profile = state.userProfile || { targetBand: 6.5, examDate: defaultExamDate() };
  const days = Math.max(0, Math.ceil((new Date(`${profile.examDate}T12:00:00`) - new Date()) / 86400000));
  const target = Number(profile.targetBand || 6.5);
  const current = overallBand();
  const weakest = Object.entries(moduleBandScores()).sort((a, b) => a[1] - b[1])[0];
  const phase = days <= 14 ? "考前校准" : days <= 42 ? "强化提分" : "能力建设";
  const focus = days <= 14 ? "用完整模考与错题复盘稳定发挥" : days <= 42 ? `集中补 ${MODULE_LABELS[weakest[0]]}，每周完成一次阶段测评` : "先建立四科稳定练习频率，再逐步增加限时训练";
  return { days, target, current, phase, focus, gap: Math.max(0, target - current) };
}

function renderPlanWeek() {
  const start = startOfWeek();
  const dayNames = ["一", "二", "三", "四", "五", "六", "日"];
  const days = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(start);
    date.setDate(start.getDate() + index);
    const iso = localDateOf(date);
    const actual = state.learningEvents.filter((event) => localDateOf(event.createdAt) === iso).reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0);
    const offset = Math.round((date - new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())) / 86400000);
    const planned = dailyPlan(Math.max(0, offset)).reduce((sum, item) => sum + Number(item.minutes || 0), 0);
    return { iso, day: dayNames[index], actual, planned, future: offset > 0, today: offset === 0 };
  });
  const plannedTotal = Math.round(state.dailyPlanBudget * 7);
  const actualTotal = days.reduce((sum, item) => sum + item.actual, 0);
  const max = Math.max(1, state.dailyPlanBudget, ...days.map((item) => item.actual));
  const bars = document.querySelector("[data-plan-week-bars]");
  if (bars) bars.innerHTML = days.map((item) => `<div class="${item.today ? "is-today" : ""}"><i><b style="height:${Math.min(100, item.actual / max * 100)}%"></b></i><strong>${item.actual || (item.future ? "·" : "0")}</strong><span>${item.day}</span></div>`).join("");
  setText("[data-plan-week-meta]", `${actualTotal} / ${plannedTotal} 分钟`);
  const milestone = examPlanMilestone();
  setText("[data-plan-milestone]", `${milestone.phase} · 距考试 ${milestone.days} 天 · 当前 ${milestone.current.toFixed(1)} → 目标 ${milestone.target.toFixed(1)}${milestone.gap ? `（差 ${milestone.gap.toFixed(1)}）` : ""}。${milestone.focus}`);
}

function stageCheckpoints() {
  const milestone = examPlanMilestone();
  const cycleCount = Math.max(1, Math.ceil(Math.max(1, milestone.days) / 14));
  const weakest = Object.entries(moduleBandScores()).sort((a, b) => a[1] - b[1]).map(([module]) => module);
  return Array.from({ length: Math.min(3, cycleCount) }, (_, index) => {
    const daysAway = Math.min(milestone.days, (index + 1) * 14);
    const date = new Date();
    date.setDate(date.getDate() + daysAway);
    const expectedBand = Math.min(milestone.target, Math.round((milestone.current + (milestone.target - milestone.current) * ((index + 1) / cycleCount)) * 2) / 2);
    const module = weakest[index % weakest.length];
    return { index: index + 1, date, daysAway, expectedBand, module, mock: index === 0 ? "完成 1 次完整模考" : "完成 1 次阶段测评" };
  });
}

function renderPlanCheckpoints() {
  const container = document.querySelector("[data-plan-checkpoints]");
  if (!container) return;
  const completedMocks = state.learningEvents.filter((event) => event.module === "Review" && event.activity === "完整阶段测评").length;
  container.innerHTML = stageCheckpoints().map((item, index) => {
    const date = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(item.date);
    return `<article class="${index === 0 ? "is-next" : ""}"><span>CHECK ${String(item.index).padStart(2, "0")}</span><strong>${date} · ${item.daysAway ? `${item.daysAway} 天后` : "今天"}</strong><p>估分目标 ≥ ${item.expectedBand.toFixed(1)} · 主攻${MODULE_LABELS[item.module]}</p><small>${item.mock}${index === 0 && completedMocks ? ` · 已累计 ${completedMocks} 次` : ""}</small></article>`;
  }).join("");
  document.querySelector("[data-plan-checkpoint-action]")?.addEventListener("click", () => showScreen("assessment"));
}

function examModeSnapshot() {
  const examDate = state.userProfile?.examDate;
  if (!examDate) return { active: false };
  const rawDays = Math.ceil((new Date(`${examDate}T12:00:00`) - new Date()) / 86400000);
  if (rawDays > 7) return { active: false };
  const tasks = {
    7: "完成最后一次完整模考；只记录问题，不临时增加新材料。",
    6: "处理模考错题，重点复盘定位句、拼写和时间分配。",
    5: "写一篇限时作文，检查结构与常见语法错误。",
    4: "完成一组听力和阅读限时训练，稳定答题节奏。",
    3: "完成口语模拟，回听并准备熟悉话题的例子。",
    2: "轻量复习错题与词汇；确认出行、证件和考试时间。",
    1: "只做轻量热身，整理物品、保证睡眠，不再做完整模考。",
    0: "今天按既定节奏完成考试；先读清题目，再稳定输出。",
  };
  return { active: true, rawDays, days: Math.max(0, rawDays), task: tasks[Math.max(0, rawDays)] || "考试后记录体感与薄弱题型，为下一轮计划提供依据。", postExam: rawDays < 0 };
}

function persistExamMode() {
  return persistValue(EXAM_MODE_KEY, JSON.stringify(state.examWeek));
}

function renderExamMode() {
  const snapshot = examModeSnapshot();
  const card = document.querySelector("[data-exam-mode]");
  if (!card) return;
  card.hidden = !snapshot.active;
  if (!snapshot.active) return;
  const checklist = [
    ["id", "确认考试证件与准考证"],
    ["route", "确认路线、到场时间与考场要求"],
    ["rest", "安排睡眠与轻量复习，不临时加量"],
  ];
  setText("[data-exam-mode-label]", snapshot.postExam ? "POST-EXAM REVIEW" : "EXAM WEEK");
  setText("[data-exam-mode-days]", snapshot.postExam ? "✓" : snapshot.days);
  setText("[data-exam-mode-title]", snapshot.postExam ? "考后复盘" : snapshot.days === 0 ? "考试当天" : `距离考试 ${snapshot.days} 天`);
  setText("[data-exam-mode-copy]", snapshot.postExam ? "把真实考场体验留下来，下一次计划会更有针对性。" : "考前不再堆叠新内容，重点是稳定正确率、节奏与状态。");
  const task = document.querySelector("[data-exam-mode-task]");
  if (task) task.innerHTML = `<strong>今天</strong><span>${escapeHtml(snapshot.task)}</span>`;
  const list = document.querySelector("[data-exam-mode-checklist]");
  if (list) list.innerHTML = snapshot.postExam ? "" : checklist.map(([id, label]) => `<label><input type="checkbox" data-exam-check="${id}" ${state.examWeek.checklist?.[id] ? "checked" : ""}><span>${label}</span></label>`).join("");
  list?.querySelectorAll("[data-exam-check]").forEach((input) => input.addEventListener("change", () => {
    state.examWeek.checklist ||= {};
    state.examWeek.checklist[input.dataset.examCheck] = input.checked;
    persistExamMode();
  }));
  const reflection = document.querySelector("[data-exam-mode-reflection]");
  const save = document.querySelector("[data-exam-mode-save]");
  if (reflection) {
    reflection.hidden = !snapshot.postExam;
    reflection.value = state.examWeek.reflection || "";
  }
  if (save) {
    save.hidden = !snapshot.postExam;
    save.onclick = () => {
      state.examWeek.reflection = reflection?.value.trim() || "";
      state.examWeek.reflectionSavedAt = new Date().toISOString();
      if (!persistExamMode()) return showToast("考后复盘未能保存，请释放存储空间后重试。", "error");
      trackLearningEvent({ module: "Review", activity: "考后复盘", durationMinutes: 5, sourceId: `exam-${state.userProfile?.examDate || localIsoDate()}` });
      showToast("考后复盘已保存，会保留在本机备份中。", "success");
    };
  }
  const practice = document.querySelector("[data-exam-mode-practice]");
  if (practice) {
    practice.textContent = snapshot.postExam ? "查看阶段分析" : snapshot.days <= 2 ? "打开错题复盘" : "打开完整模考";
    practice.onclick = () => showScreen(snapshot.postExam ? "profile" : snapshot.days <= 2 ? "graph" : "assessment");
  }
}

function renderStudyPlan() {
  const plan = dailyPlan();
  const completed = plan.filter((item) => item.complete).length;
  const nextTask = plan.find((item) => !item.complete);
  setText("[data-plan-budget-label]", state.dailyPlanBudget);
  setText("[data-plan-date]", new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "short" }).format(new Date()));
  setText("[data-plan-summary]", completed === plan.length ? "今日计划已完成。保持节奏，不需要额外加量。" : `已完成 ${completed}/${plan.length} 项；优先处理 ${MODULE_LABELS[plan.find((item) => !item.complete)?.module || plan[0].module]}。`);
  setText("[data-plan-next-title]", nextTask ? `先完成${MODULE_LABELS[nextTask.module]}` : "今日计划已完成");
  const nextAction = document.querySelector("[data-plan-next-action]");
  if (nextAction) {
    nextAction.textContent = nextTask ? nextTask.actualMinutes ? "继续这一项" : "开始这一项" : "自由练习";
    nextAction.onclick = (event) => nextTask ? startPlanTask(nextTask, event.currentTarget) : showScreen("practice");
  }
  document.querySelectorAll("[data-plan-budget]").forEach((button) => button.classList.toggle("selected", Number(button.dataset.planBudget) === state.dailyPlanBudget));
  renderPlanWeek();
  renderPlanCheckpoints();
  renderExamMode();
  renderDailyReflection();

  const list = document.querySelector("[data-daily-plan-list]");
  if (list) list.replaceChildren(...plan.map((item, index) => {
    const card = document.createElement("article");
    card.className = item.complete ? "is-complete" : "";
    card.innerHTML = `<span>0${index + 1} / ${escapeHtml(item.module.toUpperCase())}</span><div><strong>${escapeHtml(MODULE_LABELS[item.module])}</strong><em>${item.minutes} 分钟计划</em></div><p>${escapeHtml(item.summary)}</p><small>今日已练 ${item.actualMinutes} / ${item.requiredMinutes} 分钟完成线</small><div class="plan-item-actions"><button data-plan-minus aria-label="减少 5 分钟">−5</button><button data-plan-start>${item.complete ? "已完成" : item.actualMinutes ? "继续" : "开始"}</button><button data-plan-plus aria-label="增加 5 分钟">+5</button></div>`;
    card.querySelector("[data-plan-minus]").addEventListener("click", () => adjustPlanMinutes(item.module, 0, -5));
    card.querySelector("[data-plan-plus]").addEventListener("click", () => adjustPlanMinutes(item.module, 0, 5));
    card.querySelector("[data-plan-start]").addEventListener("click", (event) => startPlanTask(item, event.currentTarget));
    return card;
  }));

  const tomorrowList = document.querySelector("[data-tomorrow-plan]");
  if (tomorrowList) tomorrowList.replaceChildren(...dailyPlan(1).map((item, index) => {
    const row = document.createElement("div");
    row.innerHTML = `<span>0${index + 1}</span><strong>${escapeHtml(MODULE_LABELS[item.module])}</strong><p>${escapeHtml(item.summary)}</p><div><button data-plan-minus>−5</button><em>${item.minutes} 分</em><button data-plan-plus>+5</button></div>`;
    row.querySelector("[data-plan-minus]").addEventListener("click", () => adjustPlanMinutes(item.module, 1, -5));
    row.querySelector("[data-plan-plus]").addEventListener("click", () => adjustPlanMinutes(item.module, 1, 5));
    return row;
  }));

}

function defaultExamDate() {
  const date = new Date();
  date.setDate(date.getDate() + 90);
  return localDateOf(date);
}

function renderOnboarding() {
  const profile = state.userProfile || {};
  const target = document.querySelector("[data-onboarding-target]");
  const examDate = document.querySelector("[data-onboarding-date]");
  const level = document.querySelector("[data-onboarding-level]");
  const wordBook = document.querySelector("[data-onboarding-wordbook]");
  const newWords = document.querySelector("[data-onboarding-new-words]");
  if (target) target.value = String(profile.targetBand || "6.5");
  if (examDate) {
    examDate.min = localIsoDate();
    examDate.value = profile.examDate || defaultExamDate();
  }
  if (level) level.value = profile.level || "beginner";
  if (wordBook) wordBook.value = profile.wordBookId || "ielts-core";
  if (newWords) newWords.value = String(profile.newWordsPerDay || 8);
  state.onboardingBudget = Number(profile.dailyMinutes || state.dailyPlanBudget || 60);
  document.querySelectorAll("[data-onboarding-budget]").forEach((button) => button.classList.toggle("selected", Number(button.dataset.onboardingBudget) === state.onboardingBudget));
}

function saveOnboardingProfile({ skipDiagnostic = false } = {}) {
  const examDate = document.querySelector("[data-onboarding-date]")?.value || defaultExamDate();
  const previousWordSettings = `${state.userProfile?.wordBookId || "ielts-core"}:${state.userProfile?.newWordsPerDay || 8}`;
  state.userProfile = {
    targetBand: Number(document.querySelector("[data-onboarding-target]")?.value || 6.5),
    examDate,
    level: document.querySelector("[data-onboarding-level]")?.value || "beginner",
    dailyMinutes: state.onboardingBudget,
    wordBookId: document.querySelector("[data-onboarding-wordbook]")?.value || "ielts-core",
    newWordsPerDay: Number(document.querySelector("[data-onboarding-new-words]")?.value || 8),
    updatedAt: new Date().toISOString(),
  };
  state.dailyPlanBudget = state.onboardingBudget;
  if (!persistValue(USER_PROFILE_KEY, JSON.stringify(state.userProfile)) || !persistValue(DAILY_PLAN_KEY, String(state.dailyPlanBudget))) return showToast("学习设置未能保存，请释放存储空间后重试。", "error");
  if (previousWordSettings !== `${state.userProfile.wordBookId}:${state.userProfile.newWordsPerDay}`) removePersistedValue(DAILY_WORD_QUEUE_KEY);
  renderLearnerProfile();
  if (skipDiagnostic) showScreen("today");
  else {
    state.baselineResult = null;
    removePersistedValue(BASELINE_RESULT_KEY);
    document.querySelector("[data-baseline-form]")?.reset();
    showScreen("baseline");
  }
}

function renderBaseline() {
  const form = document.querySelector("[data-baseline-form]");
  const result = document.querySelector("[data-baseline-result]");
  if (form) form.hidden = Boolean(state.baselineResult);
  if (!result) return;
  result.hidden = !state.baselineResult;
  if (!state.baselineResult) return;
  const weakest = Object.entries(state.baselineResult.scores).sort((a, b) => a[1] - b[1])[0];
  const gap = Math.max(0, Number(state.userProfile?.targetBand || 6.5) - state.baselineResult.band);
  result.innerHTML = `<span>YOUR STARTING POINT</span><h2>初始估分 ${state.baselineResult.band.toFixed(1)}</h2><p>低可信度基线 · 目标 ${Number(state.userProfile?.targetBand || 6.5).toFixed(1)} · 差距 ${gap.toFixed(1)}</p><div>${Object.entries(state.baselineResult.scores).map(([module, score]) => `<p><strong>${MODULE_LABELS[module]}</strong><em>${score.toFixed(1)}</em></p>`).join("")}</div><h3>第一优先：${MODULE_LABELS[weakest[0]]}</h3><p>先按新的每日计划学习；完成真实练习后，估分会逐步替换这次自评基线。</p><button class="primary-action" data-baseline-plan>查看我的计划</button>`;
  result.querySelector("[data-baseline-plan]")?.addEventListener("click", () => showScreen("plan"));
}

function submitBaseline() {
  const names = ["listening", "reading", "writing", "speaking"];
  const answers = Object.fromEntries(names.map((name) => [name, document.querySelector(`input[name="baseline-${name}"]:checked`)?.value]));
  if (Object.values(answers).some((value) => !value)) {
    setText("[data-baseline-status]", "请完成四科选择，再生成初始计划。");
    return;
  }
  const scores = { Listening: Number(answers.listening), Reading: Number(answers.reading), Writing: Number(answers.writing), Speaking: Number(answers.speaking) };
  const band = IELTSLearning.explicitAverage(scores);
  const sourceId = `baseline-${localIsoDate()}`;
  state.learningEvents = state.learningEvents.filter((event) => event.sourceId !== sourceId);
  Object.entries(scores).forEach(([module, score]) => trackLearningEvent({ module, activity: "首次基线诊断", durationMinutes: 1, score, maxScore: 9, sourceId }));
  state.baselineResult = { scores, band, completedAt: new Date().toISOString() };
  persistValue(BASELINE_RESULT_KEY, JSON.stringify(state.baselineResult));
  delete state.planModules[localIsoDate()];
  persistValue(PLAN_MODULES_KEY, JSON.stringify(state.planModules));
  renderBaseline();
  refreshLearningSurfaces();
}

function renderLearnerProfile() {
  const profile = state.userProfile;
  if (!profile) return;
  setText("[data-profile-target]", Number(profile.targetBand).toFixed(1));
  const days = Math.max(0, Math.ceil((new Date(`${profile.examDate}T12:00:00`) - new Date()) / 86400000));
  setText("[data-profile-exam]", `${new Date(`${profile.examDate}T12:00:00`).toLocaleDateString("zh-CN", { month: "long", day: "numeric" })}考试 · 还剩 ${days} 天 · 每日 ${profile.dailyMinutes} 分钟`);
}

function assessmentSnapshot() {
  const scores = moduleBandScores();
  const hasBaseline = Boolean(state.baselineResult?.scores);
  const signals = IELTSLearning.learningSignals(state.learningEvents, state.baselineResult?.scores || {});
  const details = ["Listening", "Reading", "Writing", "Speaking"].map((module) => {
    const evidence = moduleEvidence(module);
    return { module, samples: evidence.events.length, required: evidence.required, ready: evidence.ready, latest: evidence.events[0] || null, score: evidence.ready || hasBaseline ? scores[module] : null };
  });
  const samples = details.reduce((sum, item) => sum + item.samples, 0);
  const completedModules = details.filter((item) => item.ready).length;
  const confidence = completedModules === 4 ? "高可信度" : hasBaseline ? "低可信度自评" : "尚未校准";
  return { details, samples, completedModules, confidence, band: signals.readyModules ? signals.band : hasBaseline ? IELTSLearning.explicitAverage(state.baselineResult.scores) : null };
}

function assessmentBlueprint() {
  return [
    { module: "Listening", practiceId: "listening-library-join", sourceId: "listening-library-join", title: "IELTS OS · Listening Sample", minutes: 12 },
    { module: "Reading", practiceId: "practice-urban-transport", sourceId: "practice-urban-transport", title: "IELTS OS · Reading Sample", minutes: 20 },
    { module: "Writing", practiceId: "task2-city-transport", sourceId: "task2-city-transport", title: "IELTS OS · Writing Sample", minutes: 40 },
    { module: "Speaking", practiceId: "speaking-hometown-part1", sourceId: "speaking-hometown-part1", title: "IELTS OS · Speaking Sample", minutes: 8 },
  ];
}

function fullMockBlueprint() {
  return assessmentBlueprint();
}

function assessmentAssignment(module) {
  return state.assessmentSession?.assignments?.find((item) => item.module === module && !state.assessmentSession.completed?.[item.practiceId]) || null;
}

function assessmentProgress() {
  const session = state.assessmentSession;
  if (!session?.startedAt) return [];
  const assignments = session.assignments || assessmentBlueprint();
  return ["Listening", "Reading", "Writing", "Speaking"].map((module) => {
    const moduleAssignments = assignments.filter((assignment) => assignment.module === module);
    const completions = moduleAssignments.filter((assignment) => session.completed?.[assignment.practiceId]);
    const assignment = moduleAssignments.find((item) => !session.completed?.[item.practiceId]) || moduleAssignments[0] || null;
    const event = completions.length === moduleAssignments.length && moduleAssignments.length ? session.completed?.[moduleAssignments[moduleAssignments.length - 1].practiceId] : null;
    return { module, assignment, assignments: moduleAssignments, completed: completions.length, total: moduleAssignments.length, event };
  });
}

function assessmentReport(session = state.assessmentSession) {
  if (!session?.completedAt) return null;
  const assignments = session.assignments || [];
  const modules = ["Listening", "Reading", "Writing", "Speaking"].map((module) => {
    const moduleAssignments = assignments.filter((item) => item.module === module);
    const ids = new Set(moduleAssignments.flatMap((item) => [item.practiceId, item.sourceId]));
    const events = state.learningEvents.filter((event) => event.module === module && ids.has(event.sourceId));
    const latest = events.slice().sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    const bands = latest.map(eventBand).filter((value) => value !== null);
    const fallback = state.baselineResult?.scores?.[module];
    const score = bands.length ? Math.round((bands.reduce((sum, value) => sum + value, 0) / bands.length) * 2) / 2 : Number.isFinite(Number(fallback)) ? Number(fallback) : null;
    const minutes = latest.reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0);
    const wrong = state.userWrongQuestions.filter((item) => moduleAssignments.some((assignment) => String(item.id || "").startsWith(assignment.practiceId))).length;
    return { module, score, minutes, target: moduleAssignments.reduce((sum, item) => sum + Number(item.minutes || 0), 0), wrong };
  });
  const weakest = modules.slice().sort((a, b) => Number(a.score !== null) - Number(b.score !== null) || (a.score ?? 9) - (b.score ?? 9) || b.wrong - a.wrong)[0];
  const totalMinutes = modules.reduce((sum, item) => sum + item.minutes, 0);
  const targetMinutes = modules.reduce((sum, item) => sum + item.target, 0);
  const completeScores = modules.every((item) => item.score !== null);
  return { modules, weakest, totalMinutes, targetMinutes, band: completeScores ? overallBand(Object.fromEntries(modules.map((item) => [item.module, item.score]))) : null };
}

function assessmentWrongItems(session = state.assessmentSession) {
  if (!session?.completedAt) return [];
  const source = state.userWrongQuestions;
  const practiceIds = new Set((session.assignments || []).map((item) => item.practiceId));
  return source.filter((item) => [...practiceIds].some((id) => String(item.id || "").startsWith(id)));
}

function openAssessmentWrongReview() {
  const items = assessmentWrongItems();
  if (!items.length) return showToast("这次模考没有可归档错题。", "success");
  const next = wrongReviewQueue(items)[0] || items.find((item) => !isWrongMastered(item)) || items[0];
  state.wrongModuleFilter = next.module;
  state.wrongQuestionTypeFilter = "全部";
  state.wrongTypeFilter = "全部";
  state.activeWrongId = next.id;
  state.wrongMode = "detail";
  showScreen("graph");
}

function markAssessmentModule(module, sourceId) {
  const assignment = state.assessmentSession?.assignments?.find((item) => item.module === module && item.sourceId === sourceId);
  if (!assignment || assignment.sourceId !== sourceId || state.assessmentSession?.completedAt) return;
  state.assessmentSession.completed ||= {};
  state.assessmentSession.completed[assignment.practiceId] = { sourceId, completedAt: new Date().toISOString() };
  if (!persistValue(ASSESSMENT_SESSION_KEY, JSON.stringify(state.assessmentSession))) return showToast("测评进度未能保存，请释放存储空间后重试。", "error");
  showToast(`阶段测评：${MODULE_LABELS[module]}已记录。`, "success");
}

function openAssessmentAssignment(assignment) {
  const item = practiceCatalog().find((entry) => entry.id === assignment.practiceId);
  if (!item) return showToast("测评题目暂不可用，请刷新题库后重试。", "error");
  openPracticeItem(item);
}

function openNextAssessmentAssignment() {
  const next = state.assessmentSession?.assignments?.find((item) => !state.assessmentSession.completed?.[item.practiceId]);
  if (next) openAssessmentAssignment(next);
  else showScreen("assessment");
}

function startAssessment() {
  if (!state.assessmentSession || state.assessmentSession.completedAt) {
    state.assessmentSession = { id: `checkpoint-${Date.now()}`, startedAt: new Date().toISOString(), completedAt: null, plan: [], assignments: assessmentBlueprint(), completed: {} };
    if (!persistValue(ASSESSMENT_SESSION_KEY, JSON.stringify(state.assessmentSession))) return showToast("测评进度未能保存，请释放存储空间后重试。", "error");
  } else if (!state.assessmentSession.assignments || Object.keys(state.assessmentSession.completed || {}).some((key) => ["Listening", "Reading", "Writing", "Speaking"].includes(key))) {
    state.assessmentSession = { ...state.assessmentSession, assignments: assessmentBlueprint(), completed: {} };
    if (!persistValue(ASSESSMENT_SESSION_KEY, JSON.stringify(state.assessmentSession))) return showToast("测评进度未能保存，请释放存储空间后重试。", "error");
  }
  renderAssessment();
  showToast("阶段测评已开始：先完成听力 Part 1。", "success");
  openNextAssessmentAssignment();
}

function startFullMock() {
  try {
    const assignments = fullMockBlueprint();
    state.assessmentSession = { id: `mock-original-${Date.now()}`, mode: "full-mock", startedAt: new Date().toISOString(), completedAt: null, plan: [], assignments, completed: {} };
    if (!persistValue(ASSESSMENT_SESSION_KEY, JSON.stringify(state.assessmentSession))) throw new Error("模考进度未能保存，请释放存储空间后重试。");
    renderAssessment();
    showToast(`IELTS OS 四科模拟已开始：共 ${assignments.length} 个步骤。`, "success");
    openNextAssessmentAssignment();
  } catch (error) {
    showToast(error.message || "该模考内容尚未完整导入。", "error");
  }
}

function finishAssessment() {
  const progress = assessmentProgress();
  if (progress.filter((item) => item.event).length < 4) {
    setText("[data-assessment-result]", "四科尚未全部完成。进度已经保存，可以稍后继续。");
    return;
  }
  const reportBeforeSave = assessmentReport({ ...state.assessmentSession, completedAt: new Date().toISOString(), scores: moduleBandScores() });
  const scores = Object.fromEntries(reportBeforeSave.modules.map((item) => [item.module, item.score]));
  const ordered = reportBeforeSave.modules.slice().sort((a, b) => Number(a.score !== null) - Number(b.score !== null) || (a.score ?? 9) - (b.score ?? 9) || b.wrong - a.wrong);
  const activity = { Listening: "精听与定位词", Reading: "限时阅读与错题复盘", Writing: "完成一篇并按四项标准修改", Speaking: "完成三轮固定追问并回听" };
  const sequence = [ordered[0].module, ordered[1].module, ordered[0].module, ordered[2].module, ordered[0].module, ordered[3].module, "Review"];
  const plan = sequence.map((module, index) => {
    const weakest = module === ordered[0].module;
    return { day: index + 1, module, task: module === "Review" ? "阶段复盘：重做本次错题并完成一次短测" : activity[module], minutes: module === "Review" ? 30 : weakest ? 40 : 25 };
  });
  state.assessmentSession = { ...state.assessmentSession, completedAt: new Date().toISOString(), band: reportBeforeSave.band, scores, plan };
  if (!persistValue(ASSESSMENT_SESSION_KEY, JSON.stringify(state.assessmentSession))) return showToast("测评结论未能保存，请释放存储空间后重试。", "error");
  trackLearningEvent({ module: "Review", activity: "完整阶段测评", durationMinutes: 5, sourceId: state.assessmentSession.id });
  renderAssessment();
  renderToday();
}

function reviewedToday(word) {
  return state.wordProgress[word]?.reviewDate === localIsoDate();
}

function currentAttempt() {
  if (!state.activePracticeId) return null;
  if (!state.attempts[state.activePracticeId]) {
    state.attempts[state.activePracticeId] = {
      answers: {}, completed: false, submitted: false, score: null, updatedAt: null, submittedAt: null,
    };
  }
  return state.attempts[state.activePracticeId];
}

async function loadJson(path, reload = false) {
  const response = await window.IELTSRemote?.get(path) || await fetch(path, reload ? { cache: "reload" } : undefined);
  if (!response.ok) throw new Error(`Failed to load ${path}`);
  return response.json();
}

const APP_DATA_SOURCES = IELTSReliability.APP_DATA_SOURCES;

function normalizeNewWordsPerDay(value) {
  return Math.max(1, Math.min(200, Math.round(Number(value) || 8)));
}

function newWordsPerDay() {
  return normalizeNewWordsPerDay(state.userProfile?.newWordsPerDay || 8);
}

function selectedBookWords() {
  const words = state.wordbook?.words || [];
  if (state.userProfile?.wordBookId === "ielts-context") return words.filter((word) => /语境/.test(word.source || ""));
  return words;
}

function dailyWordQueue() {
  const words = selectedBookWords();
  if (!words.length) return { words: [], fresh: [], review: [], deferred: 0, deferredReview: 0, cap: 40, reviewSlots: 32 };
  const date = localIsoDate();
  const bookId = state.userProfile?.wordBookId || "ielts-core";
  const signature = `v3:${date}:${bookId}:${newWordsPerDay()}:${words.length}`;
  const cached = loadStoredJson(DAILY_WORD_QUEUE_KEY, null, (value) => value && Array.isArray(value.words) && Array.isArray(value.fresh) && Array.isArray(value.review));
  if ((cached || volatileWordQueue)?.signature === signature) return { ...(cached || volatileWordQueue), presented: Number((cached || volatileWordQueue).presented || 0) };
  const queue = IELTSLearning.buildDailyQueue({ words, progress: state.wordProgress, today: date, daily: newWordsPerDay() });
  const stored = { ...queue, signature, date, bookId, presented: 0 };
  volatileWordQueue = persistValue(DAILY_WORD_QUEUE_KEY, JSON.stringify(stored)) ? null : stored;
  return stored;
}

function queueWords() {
  const words = selectedBookWords();
  return dailyWordQueue().words.map((name) => words.find((word) => word.word === name)).filter(Boolean);
}

function wordQueueCounts() {
  const queue = dailyWordQueue();
  return IELTSLearning.queueCounts({ words: queue.words, fresh: queue.fresh, progress: state.wordProgress, today: localIsoDate() });
}

function renderWordPlan(daily = newWordsPerDay(), preview = false) {
  const normalized = normalizeNewWordsPerDay(daily);
  const words = selectedBookWords();
  const queue = IELTSLearning.buildDailyQueue({ words, progress: state.wordProgress, today: localIsoDate(), daily: normalized });
  const remaining = words.filter((word) => !state.wordProgress[word.word]).length;
  const lowerBound = Math.ceil(words.length / normalized);
  const days = IELTSLearning.projectionDays({ remainingUnseen: remaining, daily: normalized, deferredReview: queue.deferredReview, reviewSlots: queue.reviewSlots });
  const input = document.querySelector("[data-word-plan-daily]");
  if (input && !preview) input.value = String(normalized);
  setText("[data-word-plan-cycle]", `约 ${days.toLocaleString("en-US")} 天 / 轮（${lowerBound.toLocaleString("en-US")} 天为无积压下限）`);
  if (!preview) {
    const deferredCopy = queue.deferredReview > 0 ? `；另有 ${queue.deferredReview} 个到期复习延后` : "";
    setText("[data-word-plan-today]", `今日：${queue.fresh.length} 个新词 + ${queue.review.length} 个复习 = ${queue.words.length} 个${deferredCopy}`);
  }
}

function saveWordPlan() {
  const input = document.querySelector("[data-word-plan-daily]");
  const daily = normalizeNewWordsPerDay(input?.value);
  state.userProfile = { ...state.userProfile, newWordsPerDay: daily, updatedAt: new Date().toISOString() };
  if (!persistValue(USER_PROFILE_KEY, JSON.stringify(state.userProfile))) return showToast("单词计划未能保存，请释放存储空间后重试。", "error");
  state.currentWordIndex = 0;
  renderWordBook();
  renderToday();
  renderStudyPlan();
  const days = Math.ceil(selectedBookWords().length / daily);
  showToast(`已更新：每日 ${daily} 个新词，约 ${days} 天完成一轮；今日另有 ${wordQueueCounts().review} 个复习词。`, "success");
}

function currentWord() {
  const words = queueWords();
  return words[state.currentWordIndex] || words[0];
}

function wordHintedToday(word) {
  return state.wordProgress[word]?.hintDate === localIsoDate();
}

function nextPendingWordIndex() {
  const words = queueWords();
  for (let offset = 1; offset <= words.length; offset += 1) {
    const index = (state.currentWordIndex + offset) % words.length;
    if (!reviewedToday(words[index].word)) return index;
  }
  return -1;
}

function advanceWordSession(message) {
  const nextIndex = nextPendingWordIndex();
  if (nextIndex < 0) renderWordSessionSummary();
  else {
    state.currentWordIndex = nextIndex;
    state.wordAppearance = null;
    persistResumeState();
    renderWordDetail();
  }
  if (message) showToast(message, "success");
}

function beginCurrentWordAppearance(item) {
  if (state.wordAppearance?.word === item.word) return true;
  const queue = dailyWordQueue();
  if (queue.presented >= queue.cap) return renderWordSessionSummary(), false;
  const appearance = IELTSLearning.beginAppearance(item.word, `card:${wordSessionId}:${++wordAppearanceSerial}`);
  if (!persistValue(DAILY_WORD_QUEUE_KEY, JSON.stringify({ ...queue, presented: queue.presented + 1 }))) return showToast("学习次数未能保存，请释放存储空间后重试。", "error"), false;
  state.wordAppearance = appearance;
  return true;
}

function revealCurrentWordDefinition() {
  const item = currentWord();
  if (!item) return;
  const previous = state.wordProgress[item.word] || {};
  state.wordProgress[item.word] = {
    ...IELTSLearning.recordFailure(previous, state.wordAppearance, localIsoDate()),
    hintDate: localIsoDate(),
    hintCount: (previous.hintDate === localIsoDate() ? previous.hintCount || 0 : 0) + 1,
    updatedAt: new Date().toISOString(),
  };
  if (!persistWordProgress()) return showToast("单词状态未能保存，请释放存储空间后重试。", "error");
  setDefinitionVisible(true);
  const result = document.querySelector("[data-word-recall-result]");
  if (result) {
    result.className = "word-recall-result is-wrong";
    result.textContent = "已查看释义；这词会在今天稍后再次出现。";
  }
}

function completeCurrentWord() {
  const item = currentWord();
  if (!item) return;
  const previous = state.wordProgress[item.word] || {};
  const neededHint = wordHintedToday(item.word);
  const result = neededHint ? "hard" : "good";
  state.wordProgress[item.word] = {
    ...IELTSLearning.recordSuccess(previous, state.wordAppearance, localIsoDate()),
    result,
    updatedAt: new Date().toISOString(),
  };
  if (!persistWordProgress()) return showToast("单词状态未能保存，请释放存储空间后重试。", "error");
  trackLearningEvent({ module: "Vocabulary", activity: neededHint ? "提示后记住" : "直接认识", durationMinutes: 1, sourceId: item.word });
  const completed = queueWords().filter((word) => reviewedToday(word.word)).length;
  advanceWordSession(`${item.word}：${neededHint ? "提示后记住" : "直接认识"}，下次按复习计划出现。今日 ${completed}/${queueWords().length}。`);
  renderDailyWords();
  renderWordBook();
  renderToday();
}

function continueAfterWordHint() {
  const item = currentWord();
  if (!item || !wordHintedToday(item.word)) return;
  advanceWordSession(`${item.word} 已放到今日清单后面。`);
}

function findWord(word) {
  const normalized = word?.toLowerCase();
  return state.wordbook?.words?.find((item) => item.word.toLowerCase() === normalized);
}

function knownWordsInText(text) {
  if (!text || !state.wordbook?.words?.length) return [];
  return state.wordbook.words
    .map((item) => item.word)
    .filter((word) => new RegExp(`\\b${escapeRegExp(word)}\\b`, "i").test(text))
    .sort((a, b) => b.length - a.length);
}

function activePassage() {
  if (!state.reading?.passages?.length) return null;
  const activeTest = state.tests?.collections
    ?.flatMap((collection) => collection.items)
    .find((item) => item.id === state.activePracticeId);
  const passageId = activeTest?.sourceId || state.reading.activePassageId;
  return state.reading.passages.find((passage) => passage.id === passageId) || state.reading.passages[0];
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderClickableParagraph(paragraph) {
  if (!paragraph?.text) return "";

  const regex = /[A-Za-z]+(?:'[A-Za-z]+)?/g;
  let cursor = 0;
  let html = "";

  for (const match of paragraph.text.matchAll(regex)) {
    const word = match[0];
    const index = match.index ?? 0;
    html += escapeHtml(paragraph.text.slice(cursor, index));
    html += `<button class="inline-word" data-lookup-word="${escapeHtml(word.toLowerCase())}" data-source-sentence="${escapeHtml(paragraph.text)}">${escapeHtml(word)}</button>`;
    cursor = index + word.length;
  }

  html += escapeHtml(paragraph.text.slice(cursor));
  return html;
}

function renderKnownWordSentence(text) {
  return renderClickableParagraph({ text });
}

function setDefinitionVisible(visible) {
  state.definitionVisible = visible;
  document.querySelectorAll("[data-word-answer-content]").forEach((element) => {
    const unavailableExample = element.hasAttribute("data-word-example-card") && element.dataset.available === "false";
    element.hidden = !visible || unavailableExample;
  });
  const decision = document.querySelector("[data-word-decision]");
  if (decision) decision.hidden = visible;
  if (!visible) {
    const result = document.querySelector("[data-word-recall-result]");
    if (result) { result.className = "word-recall-result"; result.textContent = "不看释义直接继续，代表今天已经认识。"; }
  }
}

function speakWord(word, language = "en-US") {
  if (!word) return;
  if (window.Capacitor?.Plugins?.CloudLibrary?.speak) {
    window.Capacitor.Plugins.CloudLibrary.speak({ text: word, language }).catch(() => webSpeakWord(word, language));
    return;
  }
  webSpeakWord(word, language);
}

function webSpeakWord(word, language = "en-US") {
  if (!("speechSynthesis" in window)) {
    showToast("当前浏览器不支持本地发音。");
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(word);
  utterance.lang = language;
  utterance.rate = 0.86;
  utterance.pitch = 1;

  const voices = window.speechSynthesis.getVoices();
  const voice = voices.find((item) => item.lang === language) || voices.find((item) => item.lang?.startsWith(language));
  if (voice) utterance.voice = voice;

  window.speechSynthesis.speak(utterance);
}

function shuffled(list) {
  const copy = [...list];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const target = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[target]] = [copy[target], copy[index]];
  }
  return copy;
}

function wordQuizPool() {
  const words = state.wordbook?.words || [];
  const learned = words.filter((item) => state.wordProgress[item.word]);
  if (learned.length >= 8) return learned;
  const padded = [...learned];
  for (const item of [...queueWords(), ...words]) {
    if (padded.length >= 8) break;
    if (!padded.some((entry) => entry.word === item.word)) padded.push(item);
  }
  return padded;
}

function startWordQuiz(mode = "listen") {
  const pool = wordQuizPool();
  if (pool.length < 4) {
    showToast("已学单词还太少，先完成几天今日学习再来混合复习。");
    return;
  }
  const all = state.wordbook?.words || [];
  const questions = shuffled(pool).slice(0, 10).map((item) => {
    const distractors = shuffled(all.filter((entry) => entry.word !== item.word && entry.definition !== item.definition)).slice(0, 3);
    return { word: item, options: shuffled([item, ...distractors]) };
  });
  state.wordQuiz = { mode, questions, index: 0, correct: 0, locked: false, wrong: [], sessionId: Date.now().toString(36) };
  showScreen("wordQuiz");
  renderWordQuiz();
  if (mode === "listen") setTimeout(() => speakWord(questions[0]?.word.word), 350);
}

function renderWordQuiz() {
  const quiz = state.wordQuiz;
  const question = quiz.questions[quiz.index];
  const panel = document.querySelector("[data-word-quiz-panel]");
  const summary = document.querySelector("[data-word-quiz-summary]");
  if (!panel || !question) return;
  question.appearance ||= IELTSLearning.beginAppearance(question.word.word, `quiz:${quiz.sessionId}:${quiz.index}`);
  panel.hidden = false;
  if (summary) summary.hidden = true;
  setText("[data-word-quiz-progress]", `${quiz.index + 1} / ${quiz.questions.length}`);
  const prompt = document.querySelector("[data-word-quiz-prompt]");
  if (prompt) {
    if (quiz.mode === "listen") {
      prompt.innerHTML = `<button type="button" class="word-quiz-play" data-word-quiz-replay>播放发音</button>`;
      prompt.querySelector("[data-word-quiz-replay]").addEventListener("click", () => speakWord(question.word.word));
    } else {
      prompt.innerHTML = `<p class="word-quiz-definition">${escapeHtml(question.word.definition)}</p>`;
    }
  }
  setText("[data-word-quiz-result]", quiz.mode === "listen" ? "听发音，选出正确的中文释义。" : "看释义，选出正确的英文单词。");
  const next = document.querySelector("[data-word-quiz-next]");
  if (next) next.hidden = true;
  const optionsBox = document.querySelector("[data-word-quiz-options]");
  if (!optionsBox) return;
  optionsBox.replaceChildren(...question.options.map((option) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = quiz.mode === "listen" ? option.definition : option.word;
    button.addEventListener("click", () => answerWordQuiz(option, button));
    return button;
  }));
}

function answerWordQuiz(option, button) {
  const quiz = state.wordQuiz;
  const question = quiz.questions[quiz.index];
  if (!question || quiz.locked) return;
  quiz.locked = true;
  const correct = option.word === question.word.word;
  const optionsBox = document.querySelector("[data-word-quiz-options]");
  optionsBox?.querySelectorAll("button").forEach((item) => {
    item.disabled = true;
    const isAnswer = quiz.mode === "listen" ? item.textContent === question.word.definition : item.textContent === question.word.word;
    if (isAnswer) item.classList.add("is-correct");
  });
  if (!correct) {
    button.classList.add("is-wrong");
    quiz.wrong.push(question.word.word);
    const previous = state.wordProgress[question.word.word] || {};
    state.wordProgress[question.word.word] = {
      ...IELTSLearning.recordFailure(previous, question.appearance, localIsoDate()),
      result: "hard",
      updatedAt: new Date().toISOString(),
    };
    if (quiz.questions.length < 120) quiz.questions.push({ ...question, appearance: null });
    if (!persistWordProgress()) return showToast("测验进度未能保存，请释放存储空间后重试。", "error");
  } else {
    quiz.correct += 1;
    state.wordProgress[question.word.word] = { ...IELTSLearning.recordSuccess(state.wordProgress[question.word.word], question.appearance, localIsoDate()), result: "good", updatedAt: new Date().toISOString() };
    if (!persistWordProgress()) return showToast("测验进度未能保存，请释放存储空间后重试。", "error");
  }
  trackLearningEvent({ module: "Vocabulary", activity: correct ? "混合复习答对" : "混合复习答错", durationMinutes: 1, sourceId: question.word.word });
  setText("[data-word-quiz-result]", `${correct ? "答对了" : "正确答案已标出"}：${question.word.word} ${question.word.phonetic || ""} ${question.word.definition}`.trim());
  if (quiz.mode !== "listen") speakWord(question.word.word);
  const next = document.querySelector("[data-word-quiz-next]");
  if (next) {
    next.hidden = false;
    next.textContent = quiz.index + 1 >= quiz.questions.length ? "查看结果" : "下一题";
  }
}

function advanceWordQuiz() {
  const quiz = state.wordQuiz;
  if (!quiz.locked) return;
  quiz.locked = false;
  quiz.index += 1;
  if (quiz.index < quiz.questions.length) {
    renderWordQuiz();
    if (quiz.mode === "listen") setTimeout(() => speakWord(quiz.questions[quiz.index]?.word.word), 350);
    return;
  }
  const panel = document.querySelector("[data-word-quiz-panel]");
  const summary = document.querySelector("[data-word-quiz-summary]");
  if (panel) panel.hidden = true;
  if (summary) summary.hidden = false;
  setText("[data-word-quiz-score]", `${quiz.correct} / ${quiz.questions.length}`);
  setText("[data-word-quiz-wrong]", quiz.wrong.length ? `已把 ${quiz.wrong.length} 个错词排进今日复练：${quiz.wrong.join("、")}` : "全部答对，没有新增复练词。");
  renderWordBook();
  renderDailyWords();
}

function speakText(text, label = "音频") {
  if (!text || !("speechSynthesis" in window)) {
    showToast("当前浏览器不支持本地播放。");
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  utterance.rate = 0.88;
  utterance.pitch = 1;
  const voices = window.speechSynthesis.getVoices();
  const usVoice = voices.find((voice) => voice.lang === "en-US") || voices.find((voice) => voice.lang?.startsWith("en-US"));
  if (usVoice) utterance.voice = usVoice;
  window.speechSynthesis.speak(utterance);
  showToast(`${label} 播放中。`);
}

function listeningPracticeMeta() {
  return state.practice?.practice?.find((item) => item.module === "听力");
}

function activeListeningItem() {
  const activeTest = state.tests?.collections
    ?.flatMap((collection) => collection.items)
    .find((item) => item.id === state.activePracticeId);
  const sourceId = activeTest?.sourceId || state.listening?.activeItemId;
  return state.listening?.items?.find((item) => item.id === sourceId) || state.listening?.items?.[0];
}

function speakCurrentWord(language = "en-US") {
  const item = currentWord();
  speakWord(item?.word, language);
}

function listeningVocabularyWords({ ignoreScene = false } = {}) {
  const search = state.listeningVocabSearch.trim().toLowerCase();
  return (state.wordbook?.words || [])
    .filter((item) => String(item.source || "").includes("听力核心场景词汇"))
    .filter((item) => ignoreScene || state.listeningVocabScene === "全部" || item.topic === state.listeningVocabScene)
    .filter((item) => !search || `${item.word} ${item.definition}`.toLowerCase().includes(search))
    .sort((a, b) => Number(a.bookIndex || 0) - Number(b.bookIndex || 0));
}

function listeningVocabularyScenes() {
  return [...new Set(listeningVocabularyWords({ ignoreScene: true }).map((item) => item.topic).filter(Boolean))];
}

function activeListeningVocabularyWord() {
  const words = listeningVocabularyWords();
  return words.length ? words[state.listeningVocabIndex % words.length] : null;
}

function normalizeListeningVocabulary(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function renderListeningVocabulary() {
  const scenes = listeningVocabularyScenes();
  const select = document.querySelector("[data-listening-vocab-scene]");
  if (select) {
    const values = ["全部", ...scenes];
    if (!values.includes(state.listeningVocabScene)) state.listeningVocabScene = "全部";
    select.replaceChildren(...values.map((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value === "全部" ? `全部场景 · ${listeningVocabularyWords({ ignoreScene: true }).length} 词` : value;
      return option;
    }));
    select.value = values.includes(state.listeningVocabScene) ? state.listeningVocabScene : "全部";
  }

  const search = document.querySelector("[data-listening-vocab-search]");
  if (search && search.value !== state.listeningVocabSearch) search.value = state.listeningVocabSearch;
  const words = listeningVocabularyWords();
  state.listeningVocabIndex = words.length ? state.listeningVocabIndex % words.length : 0;
  const item = activeListeningVocabularyWord();
  setText("[data-listening-vocab-topic]", item?.topic || "没有匹配的词");
  setText("[data-listening-vocab-progress]", item ? `${state.listeningVocabIndex + 1} / ${words.length}` : "0 / 0");
  setText("[data-listening-vocab-clue]", item?.definition || "换一个场景或搜索条件。 ");
  setText("[data-listening-vocab-word]", state.listeningVocabResult && item ? item.word : "••••••");
  setText("[data-listening-vocab-result]", state.listeningVocabResult?.message || "播放后输入拼写，再核对答案。");
  document.querySelector("[data-listening-vocab-check]")?.toggleAttribute("disabled", !item || Boolean(state.listeningVocabResult));
  document.querySelector("[data-listening-vocab-play]")?.toggleAttribute("disabled", !item);
}

function checkListeningVocabulary() {
  const item = activeListeningVocabularyWord();
  const input = document.querySelector("[data-listening-vocab-answer]");
  const answer = input?.value || "";
  if (!item) return;
  if (!answer.trim()) {
    setText("[data-listening-vocab-result]", "请先输入你听到的单词。");
    input?.focus();
    return;
  }

  const correct = normalizeListeningVocabulary(answer) === normalizeListeningVocabulary(item.word);
  state.listeningVocabResult = {
    correct,
    message: correct ? `正确 · ${item.word}，继续保持。` : `正确拼写是 ${item.word}。已加入错题复习。`,
  };
  trackLearningEvent({ module: "Listening", activity: "场景词听写", durationMinutes: 1, score: correct ? 1 : 0, maxScore: 1, sourceId: `scene-vocab-${item.word}` });
  if (!correct) {
    addWrongQuestion({
      id: `scene-vocab-${normalizeListeningVocabulary(item.word).replace(/[^a-z0-9]+/g, "-")}`,
      module: "Listening",
      title: "场景词听写",
      sourceMaterial: `${item.topic} · 听力核心场景词汇`,
      scene: item.topic,
      userAnswer: answer.trim(),
      correctAnswer: item.word,
      evidence: `${item.word} · ${item.definition}`,
      mistakeType: "spelling",
      aiExplanation: `你听到的是 “${item.word}”。重点检查字母顺序和词尾。`,
      reviewPoints: [item.word, item.definition, item.topic],
      nextReviewDate: tomorrowIsoDate(),
      createdAt: new Date().toISOString(),
      status: "待复盘",
    });
  }
  renderListeningVocabulary();
  renderToday();
  renderStudyPlan();
}

function nextListeningVocabulary() {
  const words = listeningVocabularyWords();
  if (!words.length) return;
  state.listeningVocabIndex = (state.listeningVocabIndex + 1) % words.length;
  state.listeningVocabResult = null;
  const input = document.querySelector("[data-listening-vocab-answer]");
  if (input) input.value = "";
  renderListeningVocabulary();
}

function lookupCopy(item, word, dictionary = state.lookupDictionary) {
  if (dictionary === "collins") {
    if (!item) {
      return `${word} is not in your local IELTS wordbook yet. Add it to the wordbook, then complete the Collins-style definition later.`;
    }

    const links = item.links?.length ? ` Related words: ${item.links.join(", ")}.` : "";
    return `${item.word}: ${item.definition.replace(/^[a-z.]+\s*/i, "")}${links}`;
  }

  if (item) return item.definition;
  return "这个词还没有收录到你的本地词书。可以先加入生词本，之后补充音标、释义和例句。";
}

function renderLookupTabs() {
  document.querySelectorAll("[data-lookup-tab]").forEach((button) => {
    const active = button.dataset.lookupTab === state.lookupDictionary;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function renderLookupDefinition() {
  const item = findWord(state.lookupWord);
  setText("[data-lookup-definition]", lookupCopy(item, state.lookupWord, state.lookupDictionary));
  renderLookupTabs();
}

function openWordLookup(word, sourceSentence = "") {
  const lookupText = word?.trim();
  if (!lookupText) return;

  const item = findWord(lookupText);
  const displayWord = item?.word || lookupText.toLowerCase();

  state.lookupWord = displayWord;
  state.lookupSourceSentence = sourceSentence || item?.ieltsExample || item?.example || "";
  state.lookupDictionary = "shanbay";
  setText("[data-lookup-title]", displayWord);
  setText("[data-lookup-phonetic]", item?.phonetic || "未收录");
  const example = sourceSentence || item?.ieltsExample || item?.example || item?.englishDefinition || item?.definition || "暂无释义";
  setText("[data-lookup-example]", example);
  setText("[data-lookup-example-label]", sourceSentence || item?.ieltsExample || item?.example ? "学习例句" : item?.englishDefinition ? "英文释义" : "释义参考");
  renderLookupDefinition();
  openSheet("word-lookup");
}

function saveLookupWord() {
  const knownItem = findWord(state.lookupWord);
  const item = knownItem || {
    word: state.lookupWord,
    phonetic: "未收录",
    definition: "未收录：待补全音标、释义和例句",
    source: "阅读点词",
    ieltsExample: state.lookupSourceSentence,
  };
  if (!item.word) return;

  const existing = state.savedWords.find((saved) => saved.word === item.word);
  const savedItem = {
    word: item.word,
    phonetic: item.phonetic,
    definition: item.definition,
    source: item.source || "阅读点词",
    sourceSentence: state.lookupSourceSentence || item.ieltsExample || item.example,
    savedAt: new Date().toISOString(),
  };

  if (existing) Object.assign(existing, savedItem);
  else state.savedWords.unshift(savedItem);

  persistSavedWords();
  renderVocabBook();
  renderWordBook();
  showToast(`${item.word} 已加入生词本。`);
  closeSheets();
}

function saveCurrentWord() {
  const item = currentWord();
  if (!item) return;
  state.lookupWord = item.word;
  state.lookupSourceSentence = item.ieltsExample || item.example || "";
  saveLookupWord();
}

function tomorrowIsoDate() {
  const date = new Date();
  date.setDate(date.getDate() + 1);
  return date.toISOString().slice(0, 10);
}

function createReadingWrongQuestion(passage, question, selectedOption) {
  const correctOption = question.options?.find((option) => option.correct);
  const review = readingQuestionReview(question);
  return {
    id: `${passage.id}-${question.id}`,
    module: "Reading",
    title: objectiveQuestionType("Reading", passage, question),
    sourceMaterial: `${passage.source} · ${question.label}`,
    userAnswer: selectedOption.id,
    userAnswerLabel: selectedOption.label,
    correctAnswer: correctOption?.id || question.answer || "",
    correctAnswerLabel: correctOption?.label || acceptedAnswerLabel(question),
    evidence: review.evidence,
    mistakeType: question.mistakeType || "reading-logic",
    aiExplanation: hasDetailedExplanation(question.aiExplanation)
      ? question.aiExplanation
      : hasDetailedExplanation(selectedOption.feedback) ? selectedOption.feedback : review.explanation,
    reviewPoints: question.reviewPoints?.length ? question.reviewPoints : [
      { label: review.evidenceLabel, value: review.evidence },
      ...(review.translation ? [{ label: "定位句意", value: review.translation }] : []),
      { label: "下次提醒", value: review.evidenceReady ? "先圈题干关键词，再回原文独立定位。" : "先根据原题面重做，再对照答案表复核。" },
    ],
    nextReviewDate: tomorrowIsoDate(),
    createdAt: new Date().toISOString(),
    status: "待复盘",
  };
}

function addWrongQuestion(item) {
  item.category = item.category || wrongTypeLabel(item.mistakeType);
  item.reviewStage ??= 0;
  const existing = state.userWrongQuestions.find((wrong) => wrong.id === item.id);
  if (existing) Object.assign(existing, item);
  else state.userWrongQuestions.unshift(item);
  persistUserWrongQuestions();
  renderWrongQuestions();
}

function isWrongMastered(item) {
  return item.status === "已掌握";
}

function isWrongDue(item, date = localIsoDate()) {
  return !isWrongMastered(item) && (!item.nextReviewDate || item.nextReviewDate <= date);
}

function wrongReviewQueue(items) {
  return items.filter((item) => isWrongDue(item)).sort((a, b) => String(a.nextReviewDate || "").localeCompare(String(b.nextReviewDate || "")) || Number(a.reviewStage || 0) - Number(b.reviewStage || 0));
}

function rateWrongQuestion(item, rating) {
  const intervals = [0, 1, 3, 7, 14, 30];
  const currentStage = Number(item.reviewStage || 0);
  const stage = rating === "again" ? 0 : Math.min(5, currentStage + (rating === "easy" ? 2 : rating === "good" ? 1 : 0));
  const interval = rating === "hard" ? 1 : intervals[stage];
  const sourceItems = state.userWrongQuestions;
  state.userWrongQuestions = sourceItems.map((wrong) => wrong.id === item.id ? {
    ...wrong,
    reviewStage: stage,
    reviewCount: Number(wrong.reviewCount || 0) + 1,
    lastReviewRating: rating,
    reviewedAt: new Date().toISOString(),
    nextReviewDate: localIsoDate(interval),
    status: stage >= 5 ? "已掌握" : "复习中",
  } : wrong);
  persistUserWrongQuestions();
  trackLearningEvent({ module: "Review", activity: item.category, durationMinutes: 3, sourceId: item.id });
  const nextDue = wrongReviewQueue(state.userWrongQuestions)[0];
  state.activeWrongId = nextDue?.id || null;
  state.wrongMode = nextDue ? "detail" : "today";
  persistResumeState();
  renderWrongQuestions();
  renderToday();
  renderStudyPlan();
  showToast(stage >= 5 ? "已掌握，本题退出日常队列。" : `已安排下次复习：${localIsoDate(interval)}。`);
}

function wrongTypeLabel(type) {
  const labels = {
    "synonym-chain": "同义替换",
    "reading-logic": "题型逻辑",
    "listening-gap-fill": "拼写与定位",
    spelling: "拼写",
    grammar: "语法",
    fluency: "流利度",
    pronunciation: "发音",
    coherence: "连贯性",
  };
  return labels[type] || "理解与策略";
}

function objectiveQuestionType(module, item, question) {
  const explicit = module === "Listening" ? String(item.meta || "").split("·")[1]?.trim() : question.type;
  const labels = {
    "Notes completion": "笔记填空",
    "Form completion": "表格填空",
    "Table completion": "表格填空",
    "Sentence completion": "句子填空",
    "Matching headings": "段落标题匹配",
    "True / False / Not Given": "判断题 T/F/NG",
    "Yes / No / Not Given": "判断题 Y/N/NG",
  };
  if (explicit && !["原题面", "Original paper"].includes(explicit)) return labels[explicit] || explicit;
  const answer = String(question.answer || "").trim().toUpperCase();
  if (["TRUE", "FALSE", "NOT GIVEN"].includes(answer)) return "判断题 T/F/NG";
  if (["YES", "NO"].includes(answer)) return "判断题 Y/N/NG";
  if (/^[A-H]$/.test(answer)) return "选择 / 匹配题";
  return module === "Listening" ? "填空题" : "原题综合";
}

function objectiveQuestionMastery() {
  const tests = (state.tests?.collections || []).flatMap((collection) => collection.items);
  const rows = {};
  for (const [practiceId, attempt] of Object.entries(state.attempts)) {
    if (!attempt?.submitted) continue;
    const sourceId = tests.find((item) => item.id === practiceId)?.sourceId || practiceId;
    const listening = state.listening?.items?.find((item) => item.id === sourceId);
    const reading = state.reading?.passages?.find((item) => item.id === sourceId);
    const item = listening || reading;
    const module = listening ? "Listening" : reading ? "Reading" : null;
    if (!item || !module) continue;
    for (const question of item.questions || []) {
      const answer = attempt.answers?.[question.id];
      if (!String(answer || "").trim()) continue;
      const type = objectiveQuestionType(module, item, question);
      const key = `${module}:${type}`;
      rows[key] ||= { module, type, total: 0, correct: 0, practiceId, submittedAt: "" };
      rows[key].total += 1;
      rows[key].correct += Number(module === "Listening" ? listeningAnswerCorrect(question, answer, item, attempt.answers) : readingAnswerCorrect(question, answer, item, attempt.answers));
      if (String(attempt.submittedAt || "") >= rows[key].submittedAt) Object.assign(rows[key], { practiceId, submittedAt: attempt.submittedAt || "" });
    }
  }
  return Object.values(rows).map((row) => ({ ...row, ratio: Math.round(row.correct / row.total * 100) })).sort((a, b) => a.ratio - b.ratio || b.total - a.total);
}

function renderWrongMasteryDashboard(items) {
  const container = document.querySelector("[data-wrong-mastery]");
  if (!container) return;
  const objective = objectiveQuestionMastery();
  const output = Object.values(items.filter((item) => ["Writing", "Speaking"].includes(item.module) && !isWrongMastered(item)).reduce((groups, item) => {
    const category = item.category || wrongTypeLabel(item.mistakeType);
    const key = `${item.module}:${category}`;
    groups[key] ||= { module: item.module, category, count: 0 };
    groups[key].count += 1;
    return groups;
  }, {})).sort((a, b) => b.count - a.count);
  const status = (row) => row.total < 3 ? "样本不足" : row.ratio >= 80 ? "较稳定" : row.ratio >= 60 ? "练习中" : "待加强";
  container.innerHTML = `<div class="section-title"><h2>题型掌握地图</h2><span>基于真实记录</span></div><p class="wrong-mastery-note">听力、阅读按已提交答案计算；写作、口语只显示复盘信号，不生成分数。</p><div class="wrong-mastery-group"><strong>听力 / 阅读</strong>${objective.length ? objective.map((row) => `<button data-mastery-practice="${escapeHtml(row.practiceId)}" data-mastery-module="${row.module}"><span>${MODULE_LABELS[row.module]} · ${escapeHtml(row.type)}<small>${row.correct}/${row.total} 题正确</small></span><i><b style="width:${row.ratio}%"></b></i><em>${row.ratio}% · ${status(row)} ›</em></button>`).join("") : '<p class="wrong-mastery-empty">提交一次听力或阅读练习后，这里会显示真实题型正确率。</p>'}</div><div class="wrong-mastery-group output"><strong>写作 / 口语训练信号</strong>${output.length ? output.map((row) => `<button data-mastery-output="${row.module}" data-mastery-category="${escapeHtml(row.category)}"><span>${MODULE_LABELS[row.module]} · ${escapeHtml(row.category)}</span><em>${row.count} 项待改进 ›</em></button>`).join("") : '<p class="wrong-mastery-empty">完成写作或口语复盘后，这里会汇总待改进项。</p>'}</div>`;
  container.querySelectorAll("[data-mastery-practice]").forEach((button) => button.addEventListener("click", () => {
    const practice = practiceCatalog().find((item) => item.id === button.dataset.masteryPractice);
    if (practice) openPracticeItem(practice, button);
    else showScreen(button.dataset.masteryModule.toLowerCase());
  }));
  container.querySelectorAll("[data-mastery-output]").forEach((button) => button.addEventListener("click", () => {
    state.wrongModuleFilter = button.dataset.masteryOutput;
    state.wrongQuestionTypeFilter = "全部";
    state.wrongTypeFilter = button.dataset.masteryCategory;
    state.wrongMode = "library";
    renderWrongQuestions();
  }));
}

function weakDrillPack(items) {
  const active = items.filter((item) => !isWrongMastered(item));
  const counts = active.reduce((result, item) => {
    const key = item.mistakeType || "understanding";
    result[key] ||= { count: 0, module: item.module };
    result[key].count += 1;
    return result;
  }, {});
  const [type, detail] = Object.entries(counts).sort(([, a], [, b]) => b.count - a.count)[0] || ["understanding", { count: 0, module: "Reading" }];
  const packs = {
    "listening-gap-fill": { title: "拼写与定位微练", minutes: 8, target: "listeningVocab", module: "Listening", steps: ["听写 5 个场景词", "回放并精听 1 句", "核对拼写与定位词"] },
    spelling: { title: "拼写稳定微练", minutes: 6, target: "listeningVocab", module: "Listening", steps: ["听写 5 个高频词", "核对易错字母", "把错误词加入复习"] },
    "synonym-chain": { title: "同义替换微练", minutes: 8, target: "reading", module: "Reading", steps: ["完成 1 个阅读定位题", "圈出题干与原文改写", "回看错题证据句"] },
    "reading-logic": { title: "阅读逻辑微练", minutes: 8, target: "reading", module: "Reading", steps: ["限时完成 1 个题型", "定位段落主旨或证据", "复盘干扰项"] },
    grammar: { title: "写作语法微练", minutes: 10, target: "writing", module: "Writing", steps: ["写一段主体段", "检查 3 处句法", "按反馈改写 1 句"] },
    coherence: { title: "口语连贯微练", minutes: 8, target: "speaking", module: "Speaking", steps: ["回答 1 个追问", "加入原因和例子", "回听并补 1 个连接句"] },
    fluency: { title: "口语流利微练", minutes: 6, target: "speaking", module: "Speaking", steps: ["连续回答 60 秒", "记录停顿位置", "再答一遍并减少停顿"] },
    pronunciation: { title: "口语发音微练", minutes: 6, target: "speaking", module: "Speaking", steps: ["朗读 3 个关键句", "回听录音", "重读重音与尾音"] },
  };
  return { ...(packs[type] || packs[detail.module === "Listening" ? "listening-gap-fill" : detail.module === "Writing" ? "grammar" : detail.module === "Speaking" ? "fluency" : "reading-logic"]), count: detail.count, type };
}

function openWeakDrill(pack) {
  if (pack.target === "reading") { state.readingMode = "questions"; renderReading(); }
  if (pack.target === "writing") { state.writingMode = "write"; renderWriting(); }
  if (pack.target === "speaking") { state.speakingMode = "conversation"; renderSpeakingCoach(); }
  showScreen(pack.target);
  showToast(`开始${pack.minutes}分钟${pack.title}：完成本轮后会自动进入学习记录。`, "success");
}

function renderWeakDrillPack(items) {
  const container = document.querySelector("[data-weak-drill-pack]");
  if (!container) return;
  const pack = weakDrillPack(items);
  container.innerHTML = `<div class="section-title"><h2>薄弱题型训练包</h2><span>${pack.minutes} 分钟</span></div><h3>${escapeHtml(pack.title)}</h3><p>来自 ${pack.count} 道未掌握错题 · ${escapeHtml(wrongTypeLabel(pack.type))}</p><ol>${pack.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ol><button class="primary-action">开始这一轮</button>`;
  container.querySelector("button")?.addEventListener("click", () => openWeakDrill(pack));
}

function renderTodayResourcePack(nextTask) {
  const container = document.querySelector("[data-today-resource-pack]");
  if (!container) return;
  const action = document.querySelector("[data-today-next-action]");
  if (action) action.onclick = null;
  const path = (state.studyPaths?.paths || []).find((item) => item.module === nextTask?.module && studyPathStatus(item) === "未开始");
  const resource = path && practiceCatalog().find((item) => item.sourceId === path.resourcePath);
  const practice = recommendedPractice(nextTask);
  container.hidden = !resource && !practice;
  if (container.hidden) return;
  const item = resource || practice;
  const label = resource ? `学习方法 / ${String(resource.resourceFormat || "资料").toUpperCase()}` : `${activeContentCourse().title} / ${practice.difficulty}`;
  container.innerHTML = `<div><span>${label}</span><strong>${escapeHtml(item.title)}</strong><p>${resource ? `先看方法，再${path.practiceLabel}` : `${escapeHtml(practice.source)} · 阶段、错题与最近训练综合排序`}</p></div><button>${resource ? "打开资料" : "开始练习"}</button>`;
  container.querySelector("button")?.addEventListener("click", (event) => {
    if (path) { state.activeStudyPathId = path.id; markStudyPathResourceOpened(path.id); }
    openPracticeItem(item, event.currentTarget);
  });
  if (action) {
    delete action.dataset.go;
    action.onclick = (event) => {
      if (path) { state.activeStudyPathId = path.id; markStudyPathResourceOpened(path.id); }
      openPracticeItem(item, event.currentTarget);
    };
  }
}

function activeContentCourse() {
  const stages = state.contentRoadmap?.stages || [];
  const stored = stages.find((stage) => stage.id === localStorage.getItem("ielts-os.coach-stage.v1"));
  if (stored) return stored;
  const calibrated = Boolean(state.baselineResult?.scores) || ["Listening", "Reading", "Writing", "Speaking"].some((module) => moduleEvidence(module).ready);
  const band = overallBand();
  const id = !calibrated || band < 5 ? "foundation" : band < 5.5 ? "method" : band < 6 ? "accuracy" : band < 6.5 ? "feedback" : "stability";
  return stages.find((stage) => stage.id === id) || { id, title: "当前课程", books: [17, 18, 19] };
}

function recommendedPractice(task) {
  const module = MODULE_LABELS[task?.module];
  if (!["听力", "阅读", "写作", "口语"].includes(module)) return null;
  const band = overallBand();
  const desired = band < 5.5 ? "基础" : band < 6.5 ? "中等" : "进阶";
  const course = activeContentCourse();
  const wrong = state.userWrongQuestions.find((item) => item.module === task.module && !isWrongMastered(item));
  const focus = wrong?.mistakeType === "synonym-chain" ? "Matching" : module === "听力" ? `Part ${band < 5.5 ? 1 : band < 6.5 ? 2 : 3}` : module === "阅读" ? `Passage ${band < 5.5 ? 1 : band < 6.5 ? 2 : 3}` : module === "写作" ? `Task ${band < 6 ? 1 : 2}` : `Part ${band < 5.5 ? 1 : 2}`;
  const recent = new Set(state.learningEvents.slice(-8).map((item) => item.sourceId));
  const available = practiceCatalog().filter((item) => item.module === module && !item.cloudOnly && !item.locked && !item.completed && !reservedForMock(item));
  const courseItems = available.filter((item) => course.books.includes(practiceIndex(item).book));
  const rank = (item) => {
    const index = practiceIndex(item);
    return Number(item.difficulty === desired) * 4 + Number(`${item.title} ${item.meta}`.includes(focus)) * 3 + Number(item.testItem) * 2 + Math.max(0, 5 - Number(index.test || 5)) - Number(recent.has(item.id)) * 6;
  };
  return (courseItems.length ? courseItems : available)
    .sort((a, b) => rank(b) - rank(a))[0] || null;
}

function reservedForMock(item) {
  return /^(?:listening|reading)-(?:17|18|19)-4-|^(?:writing|speaking)-(?:17|18|19)-test-4-/.test(item.id);
}

function startPlanTask(task, trigger) {
  const item = recommendedPractice(task);
  if (item) openPracticeItem(item, trigger);
  else showScreen(task.target);
}

function trainingDebrief(module, score, total, minutes) {
  const wrongs = state.userWrongQuestions.filter((item) => item.module === module && !isWrongMastered(item));
  const pack = weakDrillPack(wrongs);
  const next = dailyPlan().find((item) => !item.complete && item.module !== module) || dailyPlan()[0];
  window.IELTSRemote?.showDebrief?.({ module: MODULE_LABELS[module], moduleCode: module, target: MODULE_TARGETS[module], score, total, minutes, error: wrongs.length ? wrongTypeLabel(pack.type) : "本次无新增错题", pack, next });
}

function renderToday() {
  const today = state.practice?.today;
  const book = state.wordbook?.book;
  if (!today || !book) return;

  setText("[data-header-streak]", learningStreak());
  const generatedPlan = dailyPlan();

  const completedWords = queueWords().filter((item) => reviewedToday(item.word)).length;
  const todayWords = queueWords();
  setText("[data-today-word-progress]", `${completedWords} / ${todayWords.length}`);
  setText("[data-today-word-review]", `${todayWords.filter((item) => item.memoryState === "due" && !reviewedToday(item.word)).length} 个待复习`);
  const nextTask = generatedPlan.find((item) => !item.complete);
  const remainingTasks = generatedPlan.length - generatedPlan.filter((item) => item.complete).length;
  setText("[data-today-plan-first]", nextTask ? `${MODULE_LABELS[nextTask.module]} · ${nextTask.minutes} 分钟` : "今日计划已完成");
  setText("[data-today-plan-context]", nextTask ? `第一优先 · ${remainingTasks} 项待完成` : "可以自由练习或回顾错题");
  setText("[data-today-next-reason]", nextTask?.summary || "今天的计划已经完成，继续练习不会影响明天的自适应安排。");
  const nextAction = document.querySelector("[data-today-next-action]");
  if (nextAction) {
    nextAction.disabled = false;
    nextAction.dataset.go = nextTask?.target || "practice";
    nextAction.textContent = nextTask ? `开始${MODULE_LABELS[nextTask.module] || "学习"}` : "自由练习";
  }
  document.querySelector("[data-today-card]")?.setAttribute("aria-busy", "false");
  renderTodayResourcePack(nextTask);
  const completedPractice = Object.values(state.attempts).filter((attempt) => attempt.completed && attempt.submittedAt && localDateOf(attempt.submittedAt) === localIsoDate()).length;
  const wrongItems = state.userWrongQuestions;
  const pendingWrongItems = wrongReviewQueue(wrongItems);
  const metricValues = document.querySelectorAll(".screen[data-screen='today'] .metric-row strong");
  if (metricValues[0]) metricValues[0].textContent = `${completedWords}/${todayWords.length}`;
  if (metricValues[1]) metricValues[1].textContent = `${completedPractice}/2`;
  if (metricValues[2]) metricValues[2].textContent = pendingWrongItems.length;

  const taskCards = document.querySelectorAll(".screen[data-screen='today'] .task-card");
  const completedTasks = generatedPlan.filter((task) => task.complete).length;
  generatedPlan.forEach((task, index) => {
    const card = taskCards[index];
    if (!card) return;
    card.dataset.go = task.target;
    card.querySelector("strong").textContent = MODULE_LABELS[task.module];
    card.querySelector("p").textContent = task.summary;
    card.querySelector("em").textContent = `${task.minutes}min`;
    const complete = task.complete;
    card.classList.toggle("is-complete", complete);
  });
  const progress = document.querySelector("[data-today-progress]");
  if (progress) {
    progress.max = Math.max(1, generatedPlan.length);
    progress.value = completedTasks;
    progress.setAttribute("aria-label", `今日任务完成 ${completedTasks}/${generatedPlan.length}`);
  }
  setText("[data-today-progress-label]", `${completedTasks}/${generatedPlan.length}`);
  setText("[data-today-status-summary]", `${completedTasks}/${generatedPlan.length} 项完成`);

  const resumeButtons = document.querySelectorAll("[data-resume-learning]");
  const savedScreen = localStorage.getItem(LAST_SCREEN_KEY);
  const lastScreen = savedScreen === "graph" && pendingWrongItems.length === 0
    ? generatedPlan.find((task) => !task.complete)?.target || "word"
    : savedScreen || generatedPlan.find((task) => !task.complete)?.target || "word";
  const labels = { word: "继续单词", dailyWords: "继续单词", detail: "继续单词", practice: "继续练习", listening: "继续听力", listeningVocab: "继续场景词", reading: "继续阅读", writing: "继续写作", speaking: "继续口语", graph: "继续复盘", vocab: "继续生词" };
  resumeButtons.forEach((resume) => {
    resume.dataset.resumeScreen = lastScreen;
    const strong = resume.querySelector("strong");
    if (strong) strong.textContent = labels[lastScreen] || "继续学习";
    else resume.textContent = labels[lastScreen] || "继续学习";
  });

  const priorities = learningPriorities();
  document.querySelectorAll("[data-focus-tile]").forEach((tile, index) => {
    const priority = priorities[index];
    if (!priority) return;
    tile.dataset.go = priority.target;
    tile.querySelector("span").textContent = priority.module.toUpperCase();
    tile.querySelector("strong").textContent = MODULE_LABELS[priority.module];
    tile.querySelector("em").textContent = priority.reason;
  });
  const minutes = weeklyModuleMinutes();
  const totalMinutes = Object.values(minutes).reduce((sum, value) => sum + value, 0);
  const weakest = priorities[0];
  setText("[data-tutor-note]", `${MODULE_LABELS[weakest.module]}是当前优先项：${weakest.reason}。完成后系统会重新排序今日推荐。`);
  setText("[data-tutor-minutes]", Math.round(totalMinutes));
  setText("[data-tutor-weakness]", MODULE_LABELS[weakest.module]);
  setText("[data-tutor-next]", MODULE_LABELS[priorities[1]?.module || weakest.module]);
}

function renderWordBook() {
  const book = state.wordbook?.book;
  if (!book) return;

  setText(".book-cover-card h2", state.userProfile?.wordBookId === "ielts-context" ? "练习语境词汇" : "雅思核心词汇");
  setText(".book-cover-card p", `${book.learned} / ${book.total} 词`);

  renderWordPlan();
  const counts = wordQueueCounts();
  const stats = document.querySelectorAll(".screen[data-screen='word'] .word-stats strong");
  const completed = queueWords().filter((item) => reviewedToday(item.word)).length;
  if (stats[0]) stats[0].textContent = `${completed}/${counts.total}`;
  if (stats[1]) stats[1].textContent = `${counts.fresh} / ${counts.review}`;
  if (stats[2]) stats[2].textContent = state.savedWords.length;
  setText("[data-word-quiz-pool]", `${wordQuizPool().length} 词可练`);
}

function renderWordLibrary() {
  const query = state.wordLibrarySearch.trim().toLowerCase();
  const matches = (state.wordbook?.words || []).filter((item) => !query || `${item.word} ${item.definition}`.toLowerCase().includes(query));
  const visible = matches.slice(0, state.wordLibraryLimit);
  const list = document.querySelector("[data-word-library-list]");
  if (!list) return;

  setText("[data-word-library-count]", query ? `找到 ${matches.length} 词 · 已显示 ${visible.length}` : `共 ${matches.length} 词 · 已显示 ${visible.length}`);
  list.replaceChildren(...visible.map((item) => {
    const button = document.createElement("button");
    button.innerHTML = `<strong>${escapeHtml(item.word)}</strong><span>${escapeHtml(item.definition)}</span><em>${escapeHtml(item.topic || "IELTS")}</em>`;
    button.addEventListener("click", () => openWordLookup(item.word, item.ieltsExample || item.example || ""));
    return button;
  }));

  const more = document.querySelector("[data-word-library-more]");
  if (more) {
    more.hidden = visible.length >= matches.length;
    more.textContent = `继续加载（剩余 ${matches.length - visible.length}）`;
  }
}

function renderDailyWords() {
  const allWords = queueWords();
  const words = allWords.filter((item) => {
    if (state.wordFilter === "全部") return true;
    if (state.wordFilter === "已完成") return reviewedToday(item.word);
    return item.status === state.wordFilter && !reviewedToday(item.word);
  });
  const list = document.querySelector("[data-daily-word-list]");
  if (!list) return;

  document.querySelectorAll("[data-word-filter]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.wordFilter === state.wordFilter);
  });

  if (words.length === 0) {
    list.innerHTML = `<article class="empty-state"><strong>这个分类暂时没有单词</strong><p>可以返回全部清单继续学习。</p><button data-empty-reset="word">查看全部单词</button></article>`;
  } else {
    list.replaceChildren(
      ...words.map((item) => {
        const index = allWords.findIndex((word) => word.word === item.word);
        const button = document.createElement("button");
        const done = reviewedToday(item.word);
        const retry = !done && wordHintedToday(item.word);
        button.classList.toggle("completed", done);
        button.classList.toggle("needs-retry", retry);
        button.innerHTML = `<strong>${item.word}</strong><span>${item.phonetic ? `美音 ${item.phonetic}` : "点击播放系统发音"}</span><em>${done ? "今日完成" : retry ? "稍后再练" : item.status}</em>`;
        button.addEventListener("click", () => {
          state.currentWordIndex = index;
          showScreen("detail");
        });
        return button;
      })
    );
  }

  const counts = wordQueueCounts();
  const stats = document.querySelectorAll(".screen[data-screen='dailyWords'] .word-stats strong");
  if (stats[0]) stats[0].textContent = counts.fresh;
  if (stats[1]) stats[1].textContent = counts.review;
  if (stats[2]) stats[2].textContent = `${Math.max(1, Math.ceil(counts.total * 0.6))}min`;
}

function usableWordExample(text, word) {
  const sentence = String(text || "").replace(/\s+/g, " ").trim();
  if (!sentence || /^听力场景[:：]/.test(sentence) || !/[.!?]$/.test(sentence)) return false;
  if (sentence.length < 20 || sentence.length > 240 || /(?:\bQ\d+\b|->|\|\s*[A-Z]\)|\bp\.\s*\d+)/i.test(sentence)) return false;
  return new RegExp(`\\b${escapeRegExp(word)}\\b`, "i").test(sentence);
}

function wordExampleInfo(item) {
  const words = queueWords();
  const previous = words[(state.currentWordIndex - 1 + words.length) % words.length];
  const previousTexts = new Set([previous?.example, previous?.ieltsExample].filter((text) => usableWordExample(text, previous?.word)).map((text) => text.replace(/\s+/g, " ").trim()));
  const candidates = [
    { text: item.example, translation: item.exampleZh, label: "词书例句", source: item.source || "本地词书" },
    { text: item.ieltsExample, translation: item.ieltsExampleZh, label: "学习语境", source: item.source || "学习语境" },
  ];
  const selected = candidates.find((candidate) => usableWordExample(candidate.text, item.word) && !previousTexts.has(candidate.text.replace(/\s+/g, " ").trim()));
  if (!selected) return null;
  return {
    ...selected,
    text: selected.text.replace(/\s+/g, " ").trim(),
    note: selected.translation || `关键词义：${String(item.definition || "暂无中文释义").replace(/\\n/g, "；")}`,
    noteLabel: selected.translation ? "例句翻译" : "中文注释",
  };
}

function renderWordDetail() {
  const item = currentWord();
  if (!item || !beginCurrentWordAppearance(item)) return;

  const screen = document.querySelector(".screen[data-screen='detail']");
  screen?.classList.remove("session-complete");
  const summary = document.querySelector("[data-word-session-summary]");
  if (summary) summary.hidden = true;

  setText(".detail-card h2", item.word);
  setText(".pronunciation-row p", item.phonetic || "系统英文发音");
  setText("[data-word-definition]", item.definition);
  setText("[data-word-session-progress]", `已完成 ${queueWords().filter((word) => reviewedToday(word.word)).length} / ${queueWords().length}`);
  setText("[data-word-recall-prompt]", dailyWordQueue().fresh.includes(item.word) ? "新词 · 先回想中文意思" : "复习 · 先回想中文意思");
  setDefinitionVisible(false);

  const exampleCard = document.querySelector("[data-word-example-card]");
  const example = wordExampleInfo(item);
  if (exampleCard) exampleCard.dataset.available = String(Boolean(example));
  if (example) {
    const sentence = document.querySelector("[data-word-example]");
    if (sentence) sentence.innerHTML = renderKnownWordSentence(example.text);
    setText("[data-word-example-label]", example.label);
    setText("[data-word-example-zh]", `${example.noteLabel}：${example.note}`);
    setText("[data-word-example-source]", example.source);
  }

  const links = document.querySelector(".screen[data-screen='detail'] .content-card:nth-of-type(3) p");
  if (links) links.textContent = item.links?.length ? `${item.word} / ${item.links.join(" / ")} 是这一组可沉淀的关联词。` : `${item.word} 暂无关联词，完成阅读和错题后会自动补充。`;
}

function renderWordSessionSummary() {
  const words = queueWords();
  const results = words.map((item) => ({ word: item.word, ...state.wordProgress[item.word] }));
  const count = (result) => results.filter((item) => item.result === result).length;
  const weak = results.filter((item) => item.result !== "good").map((item) => item.word);
  const nextReview = results.map((item) => item.nextReviewDate).filter(Boolean).sort()[0];
  setText("[data-word-summary-score]", `直接认识 ${count("good")} · 提示后记住 ${count("hard")}`);
  setText("[data-word-summary-weak]", weak.length ? weak.join(" · ") : "本轮全部认识");
  setText("[data-word-summary-next]", nextReview === localIsoDate() ? "今天稍后" : nextReview || "明天");
  const summary = document.querySelector("[data-word-session-summary]");
  if (summary) summary.hidden = false;
  document.querySelector(".screen[data-screen='detail']")?.classList.add("session-complete");
}

function writingWordCount(text) {
  return (String(text || "").trim().match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).length;
}

function writingDraft(taskId) {
  if (!state.writingDrafts[taskId]) state.writingDrafts[taskId] = { text: "", notes: "", ideaChecks: [], history: [], updatedAt: null };
  return state.writingDrafts[taskId];
}

function renderWritingSubmitState(task, draft) {
  const words = writingWordCount(draft.text);
  const remaining = Math.max(0, 40 - words);
  setText("[data-writing-count]", words);
  setText("[data-writing-validation]", remaining
    ? `还需至少 ${remaining} 词，才能生成本地结构检查。草稿会继续自动保存。`
    : `已达到本地检查门槛；正式 ${task.type} 仍建议写满 ${task.minimumWords} 词。`);
  const submit = document.querySelector("[data-writing-submit]");
  if (submit) {
    submit.disabled = remaining > 0;
    submit.textContent = remaining ? `再写 ${remaining} 词后检查` : "提交本地检查";
  }
}

function writingStructure(text, task) {
  const paragraphs = String(text).split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
  const lower = String(text).toLowerCase();
  const checks = task.type === "Task 1"
    ? [
        ["引言", paragraphs.length >= 1],
        ["总体概述", /\b(overall|in general|it is clear)\b/.test(lower)],
        ["细节段", paragraphs.length >= 3],
        ["比较表达", /\b(higher|lower|more|less|whereas|compared)\b/.test(lower)],
      ]
    : [
        ["引言与立场", paragraphs.length >= 1 && /\b(agree|disagree|believe|argue|view)\b/.test(lower)],
        ["主体段", paragraphs.length >= 3],
        ["例子或解释", /\b(for example|for instance|because|such as)\b/.test(lower)],
        ["结论", /\b(in conclusion|to conclude|overall)\b/.test(lower)],
      ];
  return { paragraphs: paragraphs.length, checks };
}

function writingVersionDiff(currentText, previousText) {
  const words = (text) => String(text).toLowerCase().match(/[a-z]+/g) || [];
  const current = words(currentText);
  const previous = words(previousText);
  const added = [...new Set(current.filter((word) => !previous.includes(word)))].slice(0, 8);
  const removed = [...new Set(previous.filter((word) => !current.includes(word)))].slice(0, 8);
  return { wordDelta: current.length - previous.length, added, removed };
}

function renderWritingStructure(task, draft) {
  const structure = writingStructure(draft.text, task);
  const container = document.querySelector("[data-writing-structure]");
  if (!container) return;
  container.innerHTML = `<div><strong>段落结构</strong><span>${structure.paragraphs} 段</span></div>${structure.checks.map(([label, done]) => `<p class="${done ? "complete" : ""}"><b>${done ? "✓" : "○"}</b>${escapeHtml(label)}</p>`).join("")}`;
}

function personalSourceCandidates(module, availability, pattern, limit = 4) {
  return practiceCatalog().filter((entry) => entry.cloudOnly && entry.resourceModule === module && availability.includes(entry.resourceAvailability?.id)).map((entry) => ({ entry, score: pattern.test(`${entry.title} ${entry.sourceId}`) ? 1 : 0 })).sort((a, b) => b.score - a.score || a.entry.title.localeCompare(b.entry.title, "zh-CN")).slice(0, limit).map(({ entry }) => entry);
}

function renderPersonalSource({ selector, map, key, item, title, label, selectLabel = "关联", description, empty, candidates, rerender }) {
  const container = document.querySelector(selector);
  if (!container) return;
  const selected = state[map][item.id];
  container.innerHTML = `<div class="section-title"><h3>${title}</h3><span>${selected ? "已关联" : label}</span></div><p>${selected ? `当前关联：${escapeHtml(selected.title)}。${description.selected}` : description.empty}</p><div>${candidates.map((entry) => `<article><strong>${escapeHtml(entry.title)}</strong><div><button data-source-open="${escapeHtml(entry.id)}">打开</button><button data-source-select="${escapeHtml(entry.id)}">${selected?.id === entry.id ? "已关联" : selectLabel}</button></div></article>`).join("") || `<p>${empty}</p>`}</div>${selected ? '<button class="reading-source-clear" data-source-clear>取消关联</button>' : ""}`;
  container.querySelectorAll("[data-source-open]").forEach((button) => button.addEventListener("click", (event) => {
    const candidate = candidates.find((entry) => entry.id === button.dataset.sourceOpen);
    if (candidate) openPracticeItem(candidate, event.currentTarget);
  }));
  container.querySelectorAll("[data-source-select]").forEach((button) => button.addEventListener("click", () => {
    const candidate = candidates.find((entry) => entry.id === button.dataset.sourceSelect);
    if (!candidate) return;
    state[map][item.id] = { id: candidate.id, title: candidate.title, sourceId: candidate.sourceId, selectedAt: new Date().toISOString() };
    if (!persistValue(key, JSON.stringify(state[map]))) return showToast("资料关联未能保存，请释放存储空间后重试。", "error");
    rerender();
    showToast("已关联个人资料；当前训练记录会继续保留。", "success");
  }));
  container.querySelector("[data-source-clear]")?.addEventListener("click", () => {
    delete state[map][item.id];
    if (!persistValue(key, JSON.stringify(state[map]))) return showToast("取消关联未能保存，请释放存储空间后重试。", "error");
    rerender();
    showToast("已取消资料关联。");
  });
}

function renderWritingPersonalSource(task) {
  renderPersonalSource({ selector: "[data-writing-personal-source]", map: "writingSourceMap", key: WRITING_SOURCE_MAP_KEY, item: task, title: "个人写作资料", label: task.type, selectLabel: "关联本题", description: { selected: "看完后回到草稿，提纲与版本历史会继续保留。", empty: `已按 ${task.type} 筛选题库、范文和讲义；关联不代表范文可以直接套用。` }, empty: "未找到可直接预览的写作资料。", candidates: personalSourceCandidates("writing", ["preview"], task.type === "Task 1" ? /task.?1|小作文|地图|流程|图表/i : /task.?2|大作文|范文|机经|话题|题目/i), rerender: renderWriting });
}

function renderWriting() {
  const task = activeWritingTask();
  if (!task) return;
  const draft = writingDraft(task.id);

  document.querySelectorAll("[data-writing-type]").forEach((button) => {
    const selected = button.dataset.writingType === task.type;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  setText("[data-writing-source]", task.source);
  setText("[data-writing-title]", task.title);
  setText("[data-writing-prompt]", task.prompt);
  setText("[data-writing-minimum]", task.minimumWords);
  const paper = document.querySelector("[data-writing-paper]");
  if (paper) {
    const visual = task.visualAsset
      ? `<figure class="writing-source-figure"><img src="${escapeHtml(task.visualAsset)}" alt="${escapeHtml(task.title)} 原题图表" loading="lazy"><figcaption>原题图表 · 作答时请结合图中数据</figcaption></figure>`
      : task.type === "Task 1" ? '<p class="writing-source-warning">本题未附可核验图表；建议选择带图表的 Task 1 后再作答。</p>' : "";
    const text = task.questionPaper ? `<details class="writing-paper"><summary>查看原题文字</summary><pre>${escapeHtml(task.questionPaper)}</pre></details>` : "";
    paper.innerHTML = visual + text;
  }
  renderWritingPersonalSource(task);

  const textarea = document.querySelector("[data-writing-text]");
  if (textarea && textarea.value !== draft.text) textarea.value = draft.text;
  renderWritingSubmitState(task, draft);
  const notes = document.querySelector("[data-writing-notes]");
  if (notes && notes.value !== (draft.notes || "")) notes.value = draft.notes || "";
  setText("[data-writing-recovery]", draft.updatedAt ? `已恢复并自动保存 · ${new Date(draft.updatedAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}` : "草稿自动保存在本机");

  const plan = document.querySelector("[data-writing-plan-content]");
  const planButton = document.querySelector("[data-writing-plan]");
  if (plan) {
    plan.innerHTML = task.planning.map((point, index) => `<p><strong>${index + 1}</strong>${escapeHtml(point)}</p>`).join("");
    plan.hidden = !draft.planVisible;
  }
  if (planButton) {
    planButton.textContent = draft.planVisible ? "收起写作提纲" : "查看写作提纲（计为辅助）";
    planButton.setAttribute("aria-expanded", String(Boolean(draft.planVisible)));
  }
  const checklist = document.querySelector("[data-writing-idea-checklist]");
  if (checklist) checklist.replaceChildren(...task.planning.map((point, index) => {
    const button = document.createElement("button");
    const checked = (draft.ideaChecks || []).includes(index);
    button.className = checked ? "selected" : "";
    button.innerHTML = `<span>${checked ? "✓" : `0${index + 1}`}</span>${escapeHtml(point)}`;
    button.addEventListener("click", () => {
      draft.ideaChecks = checked ? draft.ideaChecks.filter((item) => item !== index) : [...(draft.ideaChecks || []), index];
      draft.updatedAt = new Date().toISOString();
      persistWritingDrafts();
      renderWriting();
    });
    return button;
  }));
  renderWritingStructure(task, draft);
  renderWritingTimer();
  renderWritingHistory(task);
  renderModuleCoachReview("Writing");
  renderWritingMode();
}

function renderPracticeStep(module, mode, title, hint, action) {
  const card = document.querySelector(`[data-practice-step="${module}"]`);
  if (!card) return;
  card.querySelector("[data-practice-step-mode]").textContent = `当前 · ${mode}`;
  card.querySelector("[data-practice-step-title]").textContent = title || "当前练习";
  card.querySelector("[data-practice-step-hint]").textContent = hint;
  card.querySelector("[data-practice-primary]").textContent = action;
}

function renderWritingMode() {
  document.querySelectorAll("[data-writing-mode]").forEach((button) => {
    const selected = button.dataset.writingMode === state.writingMode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-writing-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.writingPanel !== state.writingMode;
  });
  const task = activeWritingTask();
  const modes = {
    write: ["写作", "确认题目要求后，进入正文开始作答。", "开始写作"],
    feedback: ["检查", "查看字数、结构和连接表达建议，并据此修改下一稿。", "查看检查"],
    history: ["历史", "回看草稿版本和写作变化。", "查看历史"],
  };
  renderPracticeStep("writing", `${modes[state.writingMode][0]} · ${task?.type || "Task"}`, task?.title, modes[state.writingMode][1], modes[state.writingMode][2]);
}

function renderWritingTimer() {
  const task = activeWritingTask();
  if (!task) return;
  const remaining = Math.max(0, task.minutes * 60 - state.writingElapsedSeconds);
  const minutes = String(Math.floor(remaining / 60)).padStart(2, "0");
  const seconds = String(remaining % 60).padStart(2, "0");
  setText("[data-writing-time]", `${minutes}:${seconds}`);
  const button = document.querySelector("[data-writing-timer]");
  if (button) button.textContent = state.writingTimerId ? "暂停计时" : state.writingElapsedSeconds ? "继续计时" : "开始计时";
}

function toggleWritingTimer() {
  if (state.writingTimerId) {
    clearInterval(state.writingTimerId);
    state.writingTimerId = null;
    renderWritingTimer();
    return;
  }
  state.writingStartedAt = Date.now();
  state.writingTimerId = setInterval(() => {
    state.writingElapsedSeconds += 1;
    renderWritingTimer();
    if (activeWritingTask() && state.writingElapsedSeconds >= activeWritingTask().minutes * 60) {
      clearInterval(state.writingTimerId);
      state.writingTimerId = null;
      showToast("写作时间到，可以保存或提交分析。");
    }
  }, 1000);
  renderWritingTimer();
}

function analyzeWriting(text) {
  const words = writingWordCount(text);
  const paragraphs = String(text).split(/\n\s*\n/).filter((part) => part.trim()).length;
  const sentences = String(text).split(/[.!?]+/).filter((part) => part.trim()).length || 1;
  const connectors = (String(text).match(/\b(however|therefore|moreover|although|because|for example|in contrast|overall|while)\b/gi) || []).length;
  const unique = new Set((String(text).toLowerCase().match(/[a-z]+/g) || [])).size;
  return { words, paragraphs, sentences, connectors, unique };
}

async function submitWritingAnalysis() {
  const task = activeWritingTask();
  if (!task) return;
  const draft = writingDraft(task.id);
  const analysis = analyzeWriting(draft.text);
  if (analysis.words < 40) {
    showToast("至少写 40 个词后再生成本地结构检查。");
    return;
  }

  const entry = { id: Date.now(), submittedAt: new Date().toISOString(), text: draft.text, analysis, guidanceUsed: Boolean(draft.guidanceUsed) };
  draft.history.unshift(entry);
  draft.updatedAt = entry.submittedAt;
  if (!persistWritingDrafts()) {
    draft.history.shift();
    return showToast("写作未能保存，请释放存储空间后重试。", "error");
  }
  const reviewFocus = analysis.words < task.minimumWords
    ? { title: "完成度", type: "writing-task-response", note: `当前 ${analysis.words} 词，下一稿先补足到 ${task.minimumWords} 词。` }
    : analysis.paragraphs < 3
      ? { title: "段落结构", type: "coherence", note: "当前段落不足，下一稿先补齐主体段与结尾。" }
      : analysis.connectors < 3
        ? { title: "衔接表达", type: "coherence", note: "当前连接表达较少，下一稿补充自然的因果、转折或举例。" }
        : null;
  if (reviewFocus) addWrongQuestion({
    id: `writing-${task.id}-${entry.id}`,
    module: "Writing",
    title: `${task.type} · ${reviewFocus.title}`,
    sourceMaterial: task.title,
    userAnswer: `${reviewFocus.title}待加强`,
    correctAnswer: "下一稿修改重点",
    evidence: draft.text.slice(0, 180),
    mistakeType: reviewFocus.type,
    aiExplanation: reviewFocus.note,
    nextReviewDate: tomorrowIsoDate(),
    createdAt: entry.submittedAt,
    status: "待复盘",
  });

  const feedback = document.querySelector("[data-writing-feedback]");
  if (feedback) {
    feedback.hidden = false;
    feedback.innerHTML = `
      <article class="writing-score">
        <div><span>本地结构检查</span><strong>${analysis.words} 词</strong><p>只检查字数、段落和连接表达，不生成雅思分数。</p></div>
        <div class="score-grid">
          <span>WORDS<strong>${analysis.words}</strong></span>
          <span>PARA<strong>${analysis.paragraphs}</strong></span>
          <span>LINK<strong>${analysis.connectors}</strong></span>
          <span>VOCAB<strong>${analysis.unique}</strong></span>
        </div>
      </article>
      <article class="writing-feedback-card">
        <h3>优先修改</h3>
        <p>${analysis.words < task.minimumWords ? `当前 ${analysis.words} 词，先补足到 ${task.minimumWords} 词。` : "字数已达到要求，下一步压缩重复表达。"}</p>
        <p>${analysis.paragraphs < 3 ? "段落结构不足，建议加入清晰的主体段。" : `已识别 ${analysis.paragraphs} 个段落，结构基本完整。`}</p>
        <p>${analysis.connectors < 3 ? "连接表达较少，补充自然的转折、因果和举例。" : `检测到 ${analysis.connectors} 个连接表达，注意避免机械堆叠。`}</p>
        <p>${draft.guidanceUsed ? "本轮查看过写作提纲，已按辅助练习记录；下一稿建议先独立列提纲。" : "本轮未查看写作提纲，按独立完成记录。"}</p>
      </article>
    `;
  }
  renderWritingHistory(task);
  state.writingMode = "feedback";
  renderWritingMode();
  trackLearningEvent({ module: "Writing", activity: task.type, durationMinutes: Math.max(10, Math.round(state.writingElapsedSeconds / 60)), sourceId: task.id });
  markAssessmentModule("Writing", task.id);
  showToast("已保存本次写作和本地结构检查。");
  const focus = reviewFocus?.note || "结构已成形，下一稿压缩重复表达。";
  window.IELTSRemote?.showOutputDebrief?.({ module: "写作", headline: "本地检查完成", meta: `${analysis.words} 词 · ${analysis.paragraphs} 段`, facts: [["连接表达", `${analysis.connectors} 处`], ["完成方式", draft.guidanceUsed ? "提纲辅助" : "独立完成"]], focus, actionLabel: "按重点修改下一稿", target: "writing" });
  showModuleCoachPending("Writing");
  try {
    const aiText = await requestAI("writing_feedback", { task: { type: task.type, title: task.title, prompt: task.prompt }, essay: draft.text });
    if (aiText && feedback) {
      entry.aiFeedback = aiText;
      persistWritingDrafts();
      rememberModuleReview("Writing", aiText, { sourceId: task.id, words: analysis.words, paragraphs: analysis.paragraphs });
      const card = document.createElement("article");
      card.className = "writing-feedback-card";
      const title = document.createElement("h3");
      title.textContent = "AI 批改";
      const copy = document.createElement("div");
      copy.innerHTML = renderAgentMarkdown(aiText);
      card.append(title, copy);
      feedback.append(card);
      showToast("真实 AI 批改已返回并保存到本次记录。");
    }
  } catch (error) {
    showToast("AI 服务暂时不可用，本地分析已正常保存。");
  } finally {
    renderModuleCoachReview("Writing");
  }
}

function renderWritingHistory(task) {
  const list = document.querySelector("[data-writing-history-list]");
  if (!list) return;
  const history = writingDraft(task.id).history || [];
  list.innerHTML = history.length
    ? `<h3>提交记录</h3><div class="writing-trend" aria-label="历史字数变化">${history.slice(0, 6).reverse().map((entry) => `<div><i><b style="height:${Math.min(100, entry.analysis.words / task.minimumWords * 100)}%"></b></i><span>${entry.analysis.words}</span></div>`).join("")}</div>${history.map((entry) => `<button type="button" data-writing-version="${entry.id}"><strong>${entry.analysis.words} words · ${entry.analysis.paragraphs} 段</strong><span>${new Date(entry.submittedAt).toLocaleString("zh-CN")}</span></button>`).join("")}`
    : `<article class="empty-state"><strong>还没有提交记录</strong><p>提交后会保留文章、字数、段落和本地结构检查。</p><button data-empty-go="writing" data-empty-mode="write">开始第一篇</button></article>`;
  list.querySelectorAll("[data-writing-version]").forEach((button) => {
    button.addEventListener("click", () => {
      const entry = history.find((item) => String(item.id) === button.dataset.writingVersion);
      if (!entry) return;
      renderWritingDiff(task, entry);
      state.writingMode = "feedback";
      renderWritingMode();
    });
  });
}

function renderWritingDiff(task, entry) {
  const draft = writingDraft(task.id);
  const diff = writingVersionDiff(draft.text, entry.text);
  const container = document.querySelector("[data-writing-diff]");
  if (!container) return;
  container.hidden = false;
  container.innerHTML = `
    <div class="section-title"><h3>版本对比</h3><span>${new Date(entry.submittedAt).toLocaleDateString("zh-CN")}</span></div>
    <div class="writing-diff-stats"><p><strong>${diff.wordDelta >= 0 ? "+" : ""}${diff.wordDelta}</strong>词数变化</p><p><strong>${entry.analysis.paragraphs}</strong>历史段落</p></div>
    <p><b>新增词：</b>${escapeHtml(diff.added.join(" / ") || "无")}</p>
    <p><b>删减词：</b>${escapeHtml(diff.removed.join(" / ") || "无")}</p>
    <button type="button" data-writing-load-version>载入此版本为当前草稿</button>
  `;
  container.querySelector("[data-writing-load-version]").addEventListener("click", () => {
    draft.text = entry.text;
    draft.updatedAt = new Date().toISOString();
    persistWritingDrafts();
    renderWriting();
    showToast("历史版本已载入为当前草稿。");
  });
}

function practiceCatalog() {
  const typeByTab = { 听力: "Listening", 阅读: "Reading", 写作: "Writing", 口语: "Speaking" };
  const moduleByType = { Listening: "听力", Reading: "阅读", Writing: "写作", Speaking: "口语", Resource: "资料库" };
  const testItems = (state.tests?.collections || []).flatMap((collection) => collection.items.map((item) => ({
    ...item,
    id: item.id,
    module: moduleByType[item.type],
    source: collection.title,
    difficulty: item.locked ? "进阶" : Number(item.estimatedMinutes || 0) >= 18 ? "中等" : "基础",
    completed: Boolean(state.attempts[item.id]?.completed),
    testItem: true,
  }))).filter((item) => item.module);
  const fallbackItems = (state.practice?.practice || []).map((item, index) => ({
    ...item,
    id: `practice-${item.module}-${index}`,
    type: typeByTab[item.module],
    targetScreen: item.targetScreen || (item.module === "阅读" ? "reading" : item.module === "听力" ? "listening" : "practice"),
    difficulty: item.module === "写作" || item.module === "口语" ? "中等" : "基础",
    completed: item.module === "写作" ? Object.values(state.writingDrafts).some((draft) => draft.history?.length) : item.module === "口语" ? state.speakingSessions.length > 0 : false,
    source: item.source || "IELTS OS",
  }));
  const libraryItems = (state.libraryCatalog?.modules || []).flatMap((group) => (group.resources || []).map((resource) => ({
    id: `library:${resource.id}`,
    type: "Resource",
    module: "资料库",
    resourceModule: group.title || resource.module || "资料",
    resourceFormat: String(resource.format || "other").toLowerCase(),
    resourceAvailability: resourceAvailabilityFor(resource.format, resource.kind),
    targetScreen: "practice",
    title: resource.title,
    meta: `${String(resource.format || "file").toUpperCase()} · ${formatBytes(Number(resource.bytes || 0))}`,
    source: `个人 iCloud · ${group.title || resource.module || "资料"}`,
    sourceId: resource.path,
    cloudOnly: true,
    difficulty: "资料",
    completed: Boolean(state.resourceProgress[`library:${resource.id}`]?.completedAt),
  })));
  return [...testItems, ...fallbackItems, ...libraryItems];
}

function resourceAvailabilityFor(format, kind) {
  const normalized = String(format || "").toLowerCase();
  if (["pdf", "txt", "rtf", "doc", "docx", "ppt", "pptx", "xls", "xlsx"].includes(normalized)) return { id: "preview", label: "可直接预览", note: "iCloud 按需加载", tone: "ready" };
  if (["mp3", "m4a", "wav", "aac"].includes(normalized) || kind === "audio") return { id: "audio", label: "可播放", note: "不写入 App 包体", tone: "ready" };
  if (["mp4", "mov", "m4v"].includes(normalized) || kind === "video") return { id: "stream", label: "在线视频", note: "建议在 Wi-Fi 下播放", tone: "stream" };
  return { id: "external", label: "需在文件中打开", note: `${normalized ? normalized.toUpperCase() : "该格式"} 暂不支持应用内预览`, tone: "limited" };
}

function practiceIndex(item) {
  const text = `${item.id || ""} ${item.source || ""} ${item.title || ""} ${item.meta || ""}`;
  const book = Number(text.match(/(?:collection|pack|book)[-_ ]?(\d+)/i)?.[1]) || null;
  const test = Number(text.match(/(?:Test\s*|-(?:test-)?)([1-4])(?:\D|$)/i)?.[1]) || null;
  const sourceIds = [item.id, item.sourceId].filter(Boolean);
  const wrongItems = state.userWrongQuestions;
  const wrongCount = wrongItems.filter((wrong) => sourceIds.some((id) => String(wrong.id || "").startsWith(id))).length;
  return { book, test, wrongCount };
}

function contentQuality(module, reference = "") {
  const book = Number(String(reference).match(/(?:collection|pack|book)[-_ ]?(\d+)/i)?.[1]);
  const record = state.contentManifest?.records?.find((entry) => entry.module === module && entry.book === book);
  if (record) return record;
  return { status: "sample", label: "学习样本", media: "not-needed", mediaLabel: "" };
}

function contentQualityLabel(module, reference = "") {
  const quality = contentQuality(module, reference);
  return quality.media === "system-voice" ? `${quality.label} · ${quality.mediaLabel}` : quality.label;
}

function audioSourceFor(listeningId) {
  return state.audioMap?.items?.find((entry) => entry.listeningId === listeningId) || null;
}

async function openPracticeItem(item, trigger) {
  if (item.cloudOnly) {
    recordRecentResource(item);
    markResourceOpened(item);
    const plugin = window.Capacitor?.Plugins?.CloudLibrary;
    if (!plugin) {
      // Web fallback: the local agent server streams files from the library root.
      const endpoint = configuredAIEndpoint() || (/^https?:$/.test(location.protocol) ? location.origin : "");
      if (endpoint && item.sourceId) {
        const rel = String(item.sourceId).split("/").map(encodeURIComponent).join("/");
        window.open(`${endpoint}/library/${rel}`, "_blank", "noopener");
        return;
      }
      return showToast("请在 iPhone App 中打开云端资料；网页版只显示目录。", "error");
    }
    setButtonBusy(trigger, true, "打开中…");
    try {
      await plugin.openFile({ relativePath: item.sourceId });
    } catch (error) {
      if (error?.code !== "folder_not_selected") return showToast(error?.message || "暂时无法打开云端资料。", "error");
      try {
        await plugin.selectFolder();
        await plugin.openFile({ relativePath: item.sourceId });
      } catch (selectionError) {
        showToast(selectionError?.code === "cancelled" ? "未选择资料目录。" : selectionError?.message || "资料目录授权失败。", "error");
      }
    } finally {
      setButtonBusy(trigger, false);
    }
    return;
  }
  if (item.locked) return showToast("完成上一节后解锁这项练习。");
  const previousPracticeId = state.activePracticeId;
  if (item.testItem) state.activePracticeId = item.id;
  else if (item.module === "听力") state.activePracticeId = state.listening?.activeItemId || "listening-19-1-1";
  else if (item.module === "阅读") state.activePracticeId = "reading-demo-p1";
  if (item.targetScreen === "writing") {
    const task = state.writing?.tasks?.find((entry) => entry.id === item.sourceId);
    if (task) {
      state.activeWritingTaskId = task.id;
      state.writingElapsedSeconds = Number(writingDraft(task.id).elapsedSeconds || 0);
      state.writingMode = "write";
    }
  }
  if (item.targetScreen === "speaking") {
    const index = SPEAKING_CARDS.findIndex((card) => card.id === item.sourceId);
    if (index >= 0) selectSpeakingCard(index);
  }
  if (item.targetScreen === "reading") {
    if (state.activePracticeId !== previousPracticeId) resetReadingTransientContext();
    state.readingAnswers = currentAttempt()?.answers || {};
  }
  if (item.targetScreen === "listening") {
    state.listeningMode = trigger?.classList?.contains("catalog-main") ? "study" : "test";
    renderListening();
  }
  if (item.targetScreen === "reading") {
    const openedFromCatalog = trigger?.classList?.contains("catalog-main");
    state.readingMode = openedFromCatalog ? "article" : "questions";
    if (openedFromCatalog) state.examMode = false;
    renderReading();
  }
  showScreen(item.targetScreen);
  showToast(`已打开：${item.title}`);
}

function recordRecentResource(item) {
  const recent = { id: item.id, title: item.title, meta: item.meta || item.source || "iCloud 资料", sourceId: item.sourceId, openedAt: new Date().toISOString() };
  state.recentResources = [recent, ...state.recentResources.filter((entry) => entry.id !== recent.id)].slice(0, 8);
  persistValue(RECENT_RESOURCES_KEY, JSON.stringify(state.recentResources));
}

function openResourcePractice(item) {
  const key = String(item.resourceModule || "").toLowerCase();
  const target = ({ listening: "listeningVocab", reading: "reading", writing: "writing", speaking: "speaking", vocabulary: "detail" })[key] || "practice";
  if (target === "listeningVocab") { state.listeningMode = "study"; renderListening(); }
  if (target === "reading") { state.readingMode = "questions"; renderReading(); }
  if (target === "writing") { state.writingMode = "write"; renderWriting(); }
  if (target === "speaking") { state.speakingMode = "conversation"; renderSpeakingCoach(); }
  if (target === "detail") renderWordDetail();
  showScreen(target);
  showToast("此格式暂不支持应用内预览，已进入对应练习。", "success");
}

function markResourceOpened(item) {
  if (!item?.cloudOnly) return;
  state.resourceProgress[item.id] = { ...(state.resourceProgress[item.id] || {}), openedAt: new Date().toISOString() };
  persistValue(RESOURCE_PROGRESS_KEY, JSON.stringify(state.resourceProgress));
}

function markResourceCompleted(item) {
  if (!item?.cloudOnly) return;
  const wasCompleted = Boolean(state.resourceProgress[item.id]?.completedAt);
  state.resourceProgress[item.id] = { ...(state.resourceProgress[item.id] || {}), openedAt: state.resourceProgress[item.id]?.openedAt || new Date().toISOString(), completedAt: wasCompleted ? null : new Date().toISOString() };
  persistValue(RESOURCE_PROGRESS_KEY, JSON.stringify(state.resourceProgress));
  renderPractice();
  showToast(wasCompleted ? "已恢复为未完成。" : "资料已标记完成，会进入学习进度。", "success");
}

function renderLibraryRecents(catalog) {
  const container = document.querySelector("[data-library-recents]");
  if (!container) return;
  container.hidden = state.practiceTab !== "资料库" || !state.recentResources.length;
  if (container.hidden) return;
  const entries = state.recentResources.map((recent) => ({ recent, item: catalog.find((item) => item.id === recent.id) })).filter((entry) => entry.item);
  container.innerHTML = `<div class="section-title"><h2>继续学习</h2><span>最近打开</span></div><div>${entries.map(({ recent, item }) => `<button data-recent-resource="${escapeHtml(item.id)}"><strong>${escapeHtml(recent.title)}</strong><span>${escapeHtml(recent.meta)} · ${new Date(recent.openedAt).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}</span></button>`).join("")}</div>`;
  container.querySelectorAll("[data-recent-resource]").forEach((button) => button.addEventListener("click", (event) => {
    const item = catalog.find((entry) => entry.id === button.dataset.recentResource);
    if (item) openPracticeItem(item, event.currentTarget);
  }));
}

function openStudyPathPractice(path) {
  state.activeStudyPathId = path.id;
  if (path.practiceTarget === "reading") { state.readingMode = "questions"; renderReading(); }
  if (path.practiceTarget === "writing") { state.writingMode = "write"; renderWriting(); }
  if (path.practiceTarget === "speaking") { state.speakingMode = "conversation"; renderSpeakingCoach(); }
  showScreen(path.practiceTarget);
  showToast(`学习路径：${path.title} · 继续${path.practiceLabel}。`, "success");
}

function studyPathStatus(path) {
  const progress = state.studyPathProgress[path.id] || {};
  if (progress.practiceCompletedAt || progress.completedAt) return "已完成";
  if (progress.resourceOpenedAt) return "学习中";
  return "未开始";
}

function persistStudyPathProgress() {
  return persistValue(STUDY_PATH_PROGRESS_KEY, JSON.stringify(state.studyPathProgress));
}

function markStudyPathResourceOpened(pathId) {
  state.studyPathProgress[pathId] = { ...(state.studyPathProgress[pathId] || {}), resourceOpenedAt: new Date().toISOString() };
  persistStudyPathProgress();
}

function markStudyPathCompleted(pathId, manual = true) {
  state.studyPathProgress[pathId] = { ...(state.studyPathProgress[pathId] || {}), [manual ? "completedAt" : "practiceCompletedAt"]: new Date().toISOString() };
  persistStudyPathProgress();
  renderPractice();
}

function completeActiveStudyPath(module) {
  const path = state.studyPaths?.paths?.find((item) => item.id === state.activeStudyPathId);
  if (!path || path.module !== module) return;
  markStudyPathCompleted(path.id, false);
  state.activeStudyPathId = null;
  showToast(`学习路径已完成：${path.title}。`, "success");
}

function renderGuidedPaths() {
  const container = document.querySelector("[data-guided-paths]");
  if (!container) return;
  const visible = state.practiceTab === "资料库";
  container.hidden = !visible;
  if (!visible) return;
  const catalog = practiceCatalog();
  const paths = (state.studyPaths?.paths || []).filter((path) => !state.studyPathIncompleteOnly || studyPathStatus(path) !== "已完成");
  const completed = (state.studyPaths?.paths || []).filter((path) => studyPathStatus(path) === "已完成").length;
  container.innerHTML = `<div class="section-title"><h2>四科资料学习路径</h2><span>${completed}/${state.studyPaths?.paths?.length || 0} 完成</span></div><p>先看你的 iCloud 资料，再回到 App 完成对应练习；文件不会加入 App 包体。</p><button class="guided-path-filter" data-path-filter>${state.studyPathIncompleteOnly ? "查看全部路径" : "只看未完成"}</button><div>${paths.map((path) => `<article class="${studyPathStatus(path) === "已完成" ? "is-complete" : ""}"><span>${MODULE_LABELS[path.module] || path.module} · ${path.minutes} 分钟 · ${studyPathStatus(path)}</span><strong>${escapeHtml(path.title)}</strong><p>${escapeHtml(path.resourceTitle)}</p><div><button data-path-open="${path.id}">打开资料</button><button data-path-practice="${path.id}">${escapeHtml(path.practiceLabel)}</button><button data-path-complete="${path.id}">标记完成</button></div></article>`).join("") || "<p>所有路径已完成。</p>"}</div>`;
  container.querySelector("[data-path-filter]")?.addEventListener("click", () => { state.studyPathIncompleteOnly = !state.studyPathIncompleteOnly; renderGuidedPaths(); });
  container.querySelectorAll("[data-path-open]").forEach((button) => button.addEventListener("click", (event) => {
    const path = state.studyPaths?.paths?.find((item) => item.id === button.dataset.pathOpen);
    const resource = catalog.find((item) => item.sourceId === path?.resourcePath);
    if (!resource) return showToast("该资料暂未在目录中找到，请刷新资料库。", "error");
    markStudyPathResourceOpened(path.id);
    openPracticeItem(resource, event.currentTarget);
  }));
  container.querySelectorAll("[data-path-practice]").forEach((button) => button.addEventListener("click", () => {
    const path = state.studyPaths?.paths?.find((item) => item.id === button.dataset.pathPractice);
    if (path) openStudyPathPractice(path);
  }));
  container.querySelectorAll("[data-path-complete]").forEach((button) => button.addEventListener("click", () => {
    markStudyPathCompleted(button.dataset.pathComplete);
    showToast("路径已标记完成。", "success");
  }));
}

function togglePracticeFavorite(id) {
  state.practiceFavorites = state.practiceFavorites.includes(id) ? state.practiceFavorites.filter((item) => item !== id) : [...state.practiceFavorites, id];
  persistValue(PRACTICE_FAVORITES_KEY, JSON.stringify(state.practiceFavorites));
  renderPractice();
}

function laterModule(module) {
  return ({ 听力: "Listening", 阅读: "Reading", 写作: "Writing", 口语: "Speaking", 词汇: "Vocabulary" })[module] || module;
}

function addLaterItem(item) {
  const previous = [...state.laterItems];
  const existing = state.laterItems.find((entry) => entry.id === item.id);
  if (existing) {
    state.laterItems = state.laterItems.filter((entry) => entry.id !== item.id);
  } else {
    state.laterItems.unshift({ ...item, addedAt: new Date().toISOString() });
  }
  if (!persistValue(LATER_ITEMS_KEY, JSON.stringify(state.laterItems))) {
    state.laterItems = previous;
    return showToast("稍后学习未能保存，请释放存储空间后重试。", "error");
  }
  showToast(existing ? "已从稍后学习移除。" : "已加入稍后学习，会影响每日计划优先级。", "success");
  renderPractice();
  renderStudyPlan();
}

function addPracticeToLater(item) {
  addLaterItem({ id: `practice:${item.id}`, kind: "practice", practiceId: item.id, module: laterModule(item.module), title: item.title, meta: `${item.source || "IELTS OS"} · ${item.meta || "专项练习"}` });
}

function addCurrentWordToLater() {
  const word = currentWord();
  if (!word) return;
  addLaterItem({ id: `word:${word.word}`, kind: "word", word: word.word, module: "Vocabulary", title: word.word, meta: word.definition || "词汇复习" });
}

function openLaterItem(entry, trigger) {
  if (entry.kind === "word") {
    const index = (state.wordbook?.words || []).findIndex((word) => word.word === entry.word);
    if (index < 0) return showToast("这个单词暂时不在当前词书中。", "error");
    state.currentWordIndex = index;
    showScreen("detail");
    return;
  }
  const item = practiceCatalog().find((candidate) => candidate.id === entry.practiceId);
  if (!item) return showToast("这项内容暂不可用，请刷新题库后重试。", "error");
  openPracticeItem(item, trigger);
}

function renderLater() {
  setText("[data-later-count]", state.laterItems.length);
  setText("[data-later-summary]", state.laterItems.length ? `已保存 ${state.laterItems.length} 项；每日计划会优先照顾对应的薄弱科。` : "遇到想稍后再做的题目或单词，点击“稍后”即可放到这里。" );
  const list = document.querySelector("[data-later-list]");
  if (!list) return;
  list.replaceChildren(...(state.laterItems.length ? state.laterItems.map((entry) => {
    const card = document.createElement("article");
    card.innerHTML = `<button class="later-open"><span>${escapeHtml(MODULE_LABELS[entry.module] || entry.module)}</span><strong>${escapeHtml(entry.title)}</strong><p>${escapeHtml(entry.meta || "")}</p></button><button class="later-remove" aria-label="移除 ${escapeHtml(entry.title)}">移除</button>`;
    card.querySelector(".later-open").addEventListener("click", (event) => openLaterItem(entry, event.currentTarget));
    card.querySelector(".later-remove").addEventListener("click", () => addLaterItem(entry));
    return card;
  }) : [Object.assign(document.createElement("article"), { className: "empty-state", innerHTML: "<strong>还没有稍后学习内容</strong><p>去专项练习或单词详情，把想保留的内容加入这里。</p><button data-go=\"practice\">去找内容</button>" })]));
  list.querySelector("[data-go]")?.addEventListener("click", () => showScreen("practice"));
}

function globalLearningSearch(query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [];
  const practice = practiceCatalog().map((item) => ({ kind: "practice", item, module: item.module, search: JSON.stringify(item).toLowerCase() }));
  const words = (state.wordbook?.words || []).map((item, index) => ({ kind: "word", item, index, module: "词汇", search: `${item.word} ${item.definition} ${item.topic} ${item.example} ${item.ieltsExample}`.toLowerCase() }));
  return [...practice, ...words].filter((entry) => entry.search.includes(normalized)).slice(0, 10);
}

function renderGlobalLearningSearch(query) {
  const panel = document.querySelector("[data-global-search-results]");
  if (!panel) return;
  const results = globalLearningSearch(query);
  panel.hidden = !query.trim();
  if (!query.trim()) return;
  panel.innerHTML = `<div class="section-title"><h2>跨模块结果</h2><span>${results.length} 项</span></div>${results.length ? `<div>${results.map((result) => {
    const isWord = result.kind === "word";
    const title = isWord ? result.item.word : result.item.title;
    const meta = isWord ? `${result.item.definition || ""} · ${result.item.topic || "词汇"}` : `${result.item.source || "IELTS OS"} · ${result.item.meta || result.item.type || "练习"}`;
    return `<button data-global-search-index="${results.indexOf(result)}"><span>${escapeHtml(result.module)}</span><strong>${escapeHtml(title)}</strong><em>${escapeHtml(meta)}</em></button>`;
  }).join("")}</div>` : "<p>没有匹配内容。试试 travel、environment、口语话题或单词。</p>"}`;
  panel.querySelectorAll("[data-global-search-index]").forEach((button) => button.addEventListener("click", () => {
    const result = results[Number(button.dataset.globalSearchIndex)];
    if (!result) return;
    if (result.kind === "word") {
      state.currentWordIndex = result.index;
      showScreen("detail");
      return;
    }
    openPracticeItem(result.item, button);
  }));
}

function renderLearningRoute() {
  const card = document.querySelector("[data-learning-route]");
  if (!card) return;
  card.hidden = state.practiceTab === "资料库";
  if (card.hidden) return;
  const plan = dailyPlan();
  const nextTask = plan.find((item) => !item.complete);
  const recommendation = nextTask ? recommendedPractice(nextTask) : null;
  const course = activeContentCourse();
  const weekly = weeklyModuleMinutes();
  const weeklyGoal = Object.values(WEEKLY_GOALS).reduce((sum, value) => sum + value, 0);
  const weeklyMinutes = Object.keys(WEEKLY_GOALS).reduce((sum, module) => sum + Number(weekly[module] || 0), 0);
  const completed = plan.filter((item) => item.complete).length;
  setText("[data-learning-route-stage]", `当前阶段 · ${course.title}${course.range ? ` · Band ${course.range}` : ""}`);
  setText("[data-learning-route-week]", `本周 ${weeklyMinutes} / ${weeklyGoal} 分钟`);
  setText("[data-learning-route-title]", nextTask ? `下一课 · ${recommendation?.title || MODULE_LABELS[nextTask.module]}` : "今天的课程路线已完成");
  setText("[data-learning-route-copy]", nextTask?.summary || "今天不再追加任务；可以自由选择一科巩固，明天会重新排序路线。");
  setText("[data-learning-route-today]", `今日 ${completed} / ${plan.length} 项`);
  const progress = document.querySelector("[data-learning-route-progress]");
  if (progress) progress.style.width = `${Math.min(100, Math.round(weeklyMinutes / weeklyGoal * 100))}%`;
  const action = document.querySelector("[data-learning-route-action]");
  if (!action) return;
  action.textContent = nextTask ? nextTask.actualMinutes ? "继续下一课" : "开始下一课" : "自由练习";
  action.onclick = (event) => {
    if (nextTask) startPlanTask(nextTask, event.currentTarget);
    else showScreen(({ 听力: "listening", 阅读: "reading", 写作: "writing", 口语: "speaking" })[state.practiceTab] || "word");
  };
}

function renderLearningSubjectNext() {
  const container = document.querySelector("[data-learning-subject-next]");
  if (!container) return;
  const module = ({ 听力: "Listening", 阅读: "Reading", 写作: "Writing", 口语: "Speaking" })[state.practiceTab];
  container.hidden = !module;
  if (!module) return;
  const task = dailyPlan().find((item) => item.module === module) || { module, target: MODULE_TARGETS[module], summary: modulePlanSummary(module), actualMinutes: 0 };
  const recommendation = recommendedPractice(task);
  const descriptions = {
    Listening: "作答后查看定位解析，错题自动进入复盘。",
    Reading: "答题后查看定位和同义替换，错题自动进入复盘。",
    Writing: "写作后查看结构检查和修改方向。",
    Speaking: "录音后回听并记录改进点。",
  };
  setText("[data-learning-subject-label]", `${state.practiceTab} · NEXT STEP`);
  setText("[data-learning-subject-title]", recommendation?.title || `${state.practiceTab}专项练习`);
  setText("[data-learning-subject-copy]", descriptions[module]);
  const action = document.querySelector("[data-learning-subject-action]");
  if (!action) return;
  action.textContent = task.actualMinutes ? "继续训练" : "开始训练";
  action.onclick = (event) => startPlanTask(task, event.currentTarget);
}

function renderPractice() {
  const library = document.querySelector("[data-test-library]");
  if (!library) return;
  document.querySelectorAll("[data-practice-tab]").forEach((button) => {
    const selected = button.dataset.practiceTab === state.practiceTab;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-practice-status]").forEach((button) => button.classList.toggle("selected", button.dataset.practiceStatus === state.practiceStatus));
  const search = document.querySelector("[data-practice-search]");
  const difficulty = document.querySelector("[data-practice-difficulty]");
  const book = document.querySelector("[data-practice-book]");
  const test = document.querySelector("[data-practice-test]");
  const wrongOnly = document.querySelector("[data-practice-wrong]");
  const resourceFormat = document.querySelector("[data-practice-resource-format]");
  const resourceAvailability = document.querySelector("[data-practice-resource-availability]");
  if (search && search.value !== state.practiceSearch) search.value = state.practiceSearch;
  if (difficulty) difficulty.value = state.practiceDifficulty;
  if (wrongOnly) wrongOnly.checked = state.practiceWrongOnly;
  const allItems = practiceCatalog();
  for (const module of ["听力", "阅读", "写作", "口语"]) {
    setText(`[data-practice-module-count="${module}"]`, `${allItems.filter((item) => item.module === module).length} 项训练`);
  }
  renderLearningRoute();
  renderLearningSubjectNext();
  const moduleEnglish = { 听力: "LISTENING", 阅读: "READING", 写作: "WRITING", 口语: "SPEAKING", 资料库: "LIBRARY" };
  setText("[data-practice-current-label]", moduleEnglish[state.practiceTab] || "LEARNING");
  setText("[data-practice-current-title]", state.practiceTab === "资料库" ? "个人资料" : `更多${state.practiceTab}训练`);
  const savedScreen = localStorage.getItem(LAST_SCREEN_KEY);
  const moduleScreen = { 听力: "listening", 阅读: "reading", 写作: "writing", 口语: "speaking", 资料库: "practice" };
  const resumeTarget = ["listening", "listeningVocab", "reading", "writing", "speaking"].includes(savedScreen) ? savedScreen : moduleScreen[state.practiceTab];
  const resume = document.querySelector("[data-learning-resume]");
  if (resume) {
    resume.hidden = state.practiceTab === "资料库";
    resume.dataset.resumeScreen = resumeTarget;
    const label = ({ listening: "继续听力", listeningVocab: "继续场景词", reading: "继续阅读", writing: "继续写作", speaking: "继续口语" })[resumeTarget] || "选择资料";
    const strong = resume.querySelector("strong");
    if (strong) strong.textContent = label;
    else resume.textContent = label;
  }
  const catalog = allItems.filter((item) => item.module === state.practiceTab).map((item) => ({ ...item, index: practiceIndex(item) }));
  renderGuidedPaths();
  renderLibraryRecents(catalog);
  const books = [...new Set(catalog.map((item) => item.index.book).filter(Boolean))].sort((a, b) => b - a);
  const tests = [...new Set(catalog.map((item) => item.index.test).filter(Boolean))].sort((a, b) => a - b);
  if (book) {
    book.innerHTML = `<option value="全部">全部册数</option>${books.map((value) => `<option value="${value}">第 ${value} 册</option>`).join("")}`;
    state.practiceBook = books.includes(Number(state.practiceBook)) ? String(state.practiceBook) : "全部";
    book.value = state.practiceBook;
  }
  if (test) {
    test.innerHTML = `<option value="全部">全部 Test</option>${tests.map((value) => `<option value="${value}">Test ${value}</option>`).join("")}`;
    state.practiceTest = tests.includes(Number(state.practiceTest)) ? String(state.practiceTest) : "全部";
    test.value = state.practiceTest;
  }
  const formats = [...new Set(catalog.map((item) => item.resourceFormat).filter(Boolean))].sort();
  if (resourceFormat) {
    resourceFormat.hidden = state.practiceTab !== "资料库";
    resourceFormat.innerHTML = `<option value="全部">全部格式</option>${formats.map((value) => `<option value="${value}">${value.toUpperCase()}</option>`).join("")}`;
    state.practiceResourceFormat = formats.includes(state.practiceResourceFormat) ? state.practiceResourceFormat : "全部";
    resourceFormat.value = state.practiceResourceFormat;
  }
  if (resourceAvailability) {
    resourceAvailability.hidden = state.practiceTab !== "资料库";
    const availability = [...new Map(catalog.filter((item) => item.resourceAvailability).map((item) => [item.resourceAvailability.id, item.resourceAvailability.label])).entries()];
    resourceAvailability.innerHTML = `<option value="全部">全部可用性</option>${availability.map(([id, label]) => `<option value="${id}">${escapeHtml(label)}</option>`).join("")}`;
    state.practiceResourceAvailability = availability.some(([id]) => id === state.practiceResourceAvailability) ? state.practiceResourceAvailability : "全部";
    resourceAvailability.value = state.practiceResourceAvailability;
  }
  const query = state.practiceSearch.trim().toLowerCase();
  renderGlobalLearningSearch(query);
  const items = catalog
    .filter((item) => state.practiceBook === "全部" || item.index.book === Number(state.practiceBook))
    .filter((item) => state.practiceTest === "全部" || item.index.test === Number(state.practiceTest))
    .filter((item) => state.practiceDifficulty === "全部" || item.difficulty === state.practiceDifficulty)
    .filter((item) => state.practiceStatus === "全部" || state.practiceStatus === "收藏" && state.practiceFavorites.includes(item.id) || state.practiceStatus === "已完成" && item.completed || state.practiceStatus === "未完成" && !item.completed)
    .filter((item) => !state.practiceWrongOnly || item.index.wrongCount > 0)
    .filter((item) => state.practiceResourceFormat === "全部" || item.resourceFormat === state.practiceResourceFormat)
    .filter((item) => state.practiceResourceAvailability === "全部" || item.resourceAvailability?.id === state.practiceResourceAvailability)
    .filter((item) => !query || `${item.title} ${item.meta} ${item.source}`.toLowerCase().includes(query));
  setText("[data-practice-result-count]", items.length);
  const visibleItems = state.practiceTab === "资料库" ? items.slice(0, state.libraryLimit) : items;
  const loadMore = document.querySelector("[data-practice-load-more]");
  if (loadMore) {
    loadMore.hidden = state.practiceTab !== "资料库" || visibleItems.length >= items.length;
    loadMore.textContent = `继续加载（已显示 ${visibleItems.length}/${items.length}）`;
    loadMore.onclick = () => { state.libraryLimit += 40; renderPractice(); };
  }
  const empty = document.querySelector("[data-practice-empty]");
  if (empty) empty.hidden = items.length > 0;
  library.replaceChildren(...visibleItems.map((item) => {
    const card = document.createElement("article");
    card.className = `catalog-card ${item.locked ? "locked" : ""}`;
    const resourceProgress = item.cloudOnly ? state.resourceProgress[item.id] || {} : null;
    const status = item.cloudOnly ? item.completed ? "已完成" : resourceProgress?.openedAt ? "已打开" : "云端资料" : item.locked ? "待解锁" : item.completed ? "已完成" : "未完成";
    const quality = contentQuality(item.type, item.source);
    const qualityLabel = item.cloudOnly ? `${item.resourceAvailability.label} · ${item.resourceModule || "资料"}` : `${contentQualityLabel(item.type, item.source)}${item.teachingReview?.status === "human-reviewed" ? " · 逐题人工精校" : ""}`;
    const indexLabel = item.index.book ? `C${item.index.book}${item.index.test ? ` · Test ${item.index.test}` : ""}` : "IELTS OS";
    const laterId = `practice:${item.id}`;
    card.innerHTML = `<button class="catalog-main" title="${escapeHtml(item.cloudOnly ? item.resourceAvailability.note : "")}"><span>${indexLabel} · ${escapeHtml(item.difficulty)}</span><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.meta)}</p><div class="content-quality"><b class="${item.cloudOnly ? item.resourceAvailability.tone : quality.status === "ready" ? "ready" : "sample"}">${escapeHtml(qualityLabel)}</b><em>${item.index.wrongCount ? `${item.index.wrongCount} 道错题` : status}</em></div></button><div class="catalog-actions">${item.cloudOnly && item.resourceAvailability.id === "external" ? `<button class="catalog-resource-practice">去练习</button>` : ""}${item.cloudOnly ? `<button class="catalog-resource-complete">${item.completed ? "重做" : "完成"}</button>` : ""}<button class="catalog-later" aria-label="${state.laterItems.some((entry) => entry.id === laterId) ? "移除稍后学习" : "加入稍后学习"}">${state.laterItems.some((entry) => entry.id === laterId) ? "已稍后" : "稍后"}</button><button class="catalog-favorite" aria-label="${state.practiceFavorites.includes(item.id) ? "取消收藏" : "收藏"}${escapeHtml(item.title)}">${state.practiceFavorites.includes(item.id) ? "已收藏" : "收藏"}</button></div>`;
    card.querySelector(".catalog-main").addEventListener("click", (event) => openPracticeItem(item, event.currentTarget));
    card.querySelector(".catalog-favorite").addEventListener("click", () => togglePracticeFavorite(item.id));
    card.querySelector(".catalog-later").addEventListener("click", () => addPracticeToLater(item));
    card.querySelector(".catalog-resource-complete")?.addEventListener("click", () => markResourceCompleted(item));
    card.querySelector(".catalog-resource-practice")?.addEventListener("click", () => openResourcePractice(item));
    return card;
  }));
  window.IELTSRemote?.renderLibraryCenter?.();
}

function listeningPersonalMediaCandidates(item) {
  const audio = practiceCatalog().filter((entry) => entry.cloudOnly && entry.resourceModule === "listening" && entry.resourceAvailability?.id === "audio");
  const terms = `${item.meta || ""} ${item.vocabularyTopic || ""} ${item.title || ""}`.toLowerCase().match(/[\u4e00-\u9fa5a-z0-9]+/gi) || [];
  return audio.map((entry) => ({ entry, score: terms.reduce((total, term) => total + (entry.title.toLowerCase().includes(term) || entry.sourceId.toLowerCase().includes(term) ? 2 : 0), 0) + (/语料训练|听写|横向测试|纵向测试/.test(entry.title) ? 1 : 0) }))
    .sort((a, b) => b.score - a.score || a.entry.title.localeCompare(b.entry.title, "zh-CN"))
    .slice(0, 4)
    .map(({ entry }) => entry);
}

function hasReliableEvidence(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text || /^Practice collection \d+ · Test \d+/i.test(text)) return false;
  return (text.match(/[A-Za-z]+(?:'[A-Za-z]+)?/g) || []).length >= 5;
}

function hasDetailedExplanation(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return Boolean(text) && !/^正确答案[:：]/.test(text);
}

function listeningQuestionReview(question) {
  const evidenceReady = hasReliableEvidence(question.evidence);
  return {
    evidenceLabel: evidenceReady ? "定位句" : "来源",
    evidence: question.evidence || "本地答案表",
    translation: String(question.evidenceTranslation || "").trim(),
    explanation: hasDetailedExplanation(question.explanation)
      ? question.explanation
      : "本地暂未录入逐题解析；请结合上方原题面和答案复核。",
  };
}

function acceptedAnswerLabel(question) {
  const aliases = question.aliases || [question.answer];
  return question.answerGroup && aliases.length > 1 ? `${aliases.join(" / ")}（顺序可互换）` : question.answer || "";
}

function aliasAnswerCorrect(question, value, questions = [], answers = {}) {
  const normalized = String(value || "").trim().toLowerCase();
  const accepted = (question.aliases || [question.answer]).some((answer) => String(answer).trim().toLowerCase() === normalized);
  if (!accepted || !question.answerGroup) return accepted;
  const group = questions.filter((item) => item.answerGroup === question.answerGroup);
  const groupAnswers = group.map((item) => String(answers[item.id] || "").trim().toLowerCase()).filter(Boolean);
  return groupAnswers.length === group.length && new Set(groupAnswers).size === group.length;
}

function markListeningSentenceHint() {
  const attempt = currentAttempt();
  if (!attempt) return;
  attempt.dictationHints = { ...(attempt.dictationHints || {}), [state.listeningSentenceIndex]: true };
  attempt.updatedAt = new Date().toISOString();
  if (!persistAttempts()) return setText("[data-listening-dictation-result]", "听写结果未能保存，请释放存储空间后重试。");
}

function renderListeningPersonalMedia(item) {
  const container = document.querySelector("[data-listening-personal-media]");
  if (!container) return;
  const selected = state.listeningAuxMedia[item.id];
  const manualMap = state.listeningManualMap[item.id];
  const candidates = listeningPersonalMediaCandidates(item);
  const candidateList = candidates.map((entry) => `<article><strong>${escapeHtml(entry.title)}</strong><span>${escapeHtml(entry.meta)}</span><div><button data-listening-aux-open="${escapeHtml(entry.id)}">打开</button><button data-listening-aux-select="${escapeHtml(entry.id)}">${selected?.id === entry.id ? "已选" : "设为辅助"}</button></div></article>`).join("") || "<p>资料库中暂未找到可播放的个人音频。</p>";
  container.innerHTML = `<div class="section-title"><h3>个人听力素材</h3><span>${manualMap ? "已手动映射" : "非本节原声"}</span></div><p>${manualMap ? `你已确认：${escapeHtml(manualMap.title)} 对应本节。该映射由你手动确认，尚未经过自动校验。` : selected ? `当前辅助素材：${escapeHtml(selected.title)}。` : "本节原声仍待匹配；当前请使用系统朗读练习。"}</p><details ${selected || manualMap ? "open" : ""}><summary>查看 ${candidates.length} 个候选辅助音频（需自行核对）</summary><div>${candidateList}</div></details>${selected ? `<div class="listening-manual-map"><button data-listening-map-confirm>${manualMap ? "更新为当前素材" : "确认对应本节"}</button>${manualMap ? '<button data-listening-map-clear>取消映射</button>' : ""}<small>请在听过音频并核对题目后再确认；不会改变官方原声校验状态。</small></div>` : ""}`;
  container.querySelectorAll("[data-listening-aux-open]").forEach((button) => button.addEventListener("click", (event) => {
    const candidate = candidates.find((entry) => entry.id === button.dataset.listeningAuxOpen);
    if (candidate) openPracticeItem(candidate, event.currentTarget);
  }));
  container.querySelectorAll("[data-listening-aux-select]").forEach((button) => button.addEventListener("click", () => {
    const candidate = candidates.find((entry) => entry.id === button.dataset.listeningAuxSelect);
    if (!candidate) return;
    state.listeningAuxMedia[item.id] = { id: candidate.id, title: candidate.title, sourceId: candidate.sourceId, selectedAt: new Date().toISOString() };
    persistValue(LISTENING_AUX_MEDIA_KEY, JSON.stringify(state.listeningAuxMedia));
    renderListeningPersonalMedia(item);
    showToast("已设为辅助素材；它不会被标记为本节原声。", "success");
  }));
  container.querySelector("[data-listening-map-confirm]")?.addEventListener("click", () => {
    const current = state.listeningAuxMedia[item.id];
    if (!current) return;
    state.listeningManualMap[item.id] = { ...current, confirmedAt: new Date().toISOString() };
    persistValue(LISTENING_MANUAL_MAP_KEY, JSON.stringify(state.listeningManualMap));
    renderListening();
    showToast("已保存本节手动映射；自动原声校验仍保持独立。", "success");
  });
  container.querySelector("[data-listening-map-clear]")?.addEventListener("click", () => {
    delete state.listeningManualMap[item.id];
    persistValue(LISTENING_MANUAL_MAP_KEY, JSON.stringify(state.listeningManualMap));
    renderListening();
    showToast("已取消本节手动映射。");
  });
}

function renderListening() {
  const item = activeListeningItem();
  if (!item) return;
  const quality = contentQuality("Listening", item.source);
  const audioSource = audioSourceFor(item.id);
  setText("[data-listening-source]", item.source);
  setText("[data-listening-title]", item.title);
  setText("[data-listening-meta]", item.meta);
  const manualMap = state.listeningManualMap[item.id];
  const mediaStatus = audioSource?.status === "ready" ? "已匹配个人原版音频" : manualMap ? "已手动映射个人音频 · 待自动校验" : "原版音频待匹配 · 当前为系统朗读练习";
  const teachingStatus = item.teachingReview?.status === "human-reviewed" ? " · 逐题人工精校" : "";
  setText("[data-listening-rights]", item.sourcePages ? `个人 iCloud 来源 · ${quality.label}${teachingStatus} · ${mediaStatus} · 题面 p.${item.sourcePages.questions} · 答案 p.${item.sourcePages.answers}` : "练习内容来源说明");
  setText("[data-listening-script]", item.audioScript);
  setText("[data-listening-script-translation]", item.audioScriptTranslation || "暂无中文翻译。");
  const relatedWords = (state.wordbook?.words || []).filter((word) => word.topic === item.vocabularyTopic);
  setText("[data-listening-vocab-link]", item.vocabularyTopic ? `${item.vocabularyTopic} · ${relatedWords.length} 词` : "打开全部场景词");
  const relatedList = document.querySelector("[data-listening-related-words]");
  if (relatedList) relatedList.replaceChildren(...relatedWords.slice(0, 5).map((word) => {
    const chip = document.createElement("span");
    chip.textContent = word.word;
    return chip;
  }));
  const transcriptPanel = document.querySelector("[data-listening-transcript-panel]");
  const transcriptButton = document.querySelector("[data-listening-transcript]");
  const translationButton = document.querySelector("[data-listening-translation]");
  const translatedScript = document.querySelector("[data-listening-script-translation]");
  if (transcriptPanel) transcriptPanel.hidden = !state.listeningTranscriptVisible;
  if (translatedScript) translatedScript.hidden = !state.listeningTranslationVisible;
  if (transcriptButton) {
    transcriptButton.textContent = state.listeningTranscriptVisible ? "隐藏原文" : "显示原文";
    transcriptButton.setAttribute("aria-expanded", String(state.listeningTranscriptVisible));
  }
  if (translationButton) {
    const translationReady = Boolean(String(item.audioScriptTranslation || "").trim());
    if (!translationReady) state.listeningTranslationVisible = false;
    translationButton.disabled = !translationReady;
    translationButton.textContent = translationReady ? (state.listeningTranslationVisible ? "隐藏翻译" : "显示翻译") : "暂无中文翻译";
    translationButton.setAttribute("aria-expanded", String(state.listeningTranslationVisible));
  }
  renderNativeAudioPlayer(item);
  renderListeningPersonalMedia(item);
  renderListeningSentence(item);
  renderListeningMode();

  const task = document.querySelector("[data-listening-task]");
  if (!task) return;
  const attempt = currentAttempt();
  const submitted = Boolean(attempt?.submitted && state.activePracticeId.startsWith("listening"));
  const answers = attempt?.answers || {};
  const answered = item.questions.filter((question) => String(answers[question.id] || "").trim()).length;
  const correct = item.questions.filter((question) => listeningAnswerCorrect(question, answers[question.id])).length;

  task.replaceChildren();
  const heading = document.createElement("div");
  heading.innerHTML = `<span>${escapeHtml(item.meta)}</span><h3>完成原题后填写答案</h3>${item.questionPaper ? `<details class="listening-paper" open><summary>查看原题面</summary><pre>${escapeHtml(item.questionPaper)}</pre></details>` : ""}`;
  task.append(heading);

  for (const question of item.questions) {
    const label = document.createElement("label");
    label.textContent = `${question.number}. ${question.prompt}`;
    const input = document.createElement("input");
    input.value = answers[question.id] || "";
    input.placeholder = question.placeholder;
    input.disabled = submitted;
    input.dataset.listeningAnswer = question.id;
    if (submitted) input.classList.add(listeningAnswerCorrect(question, input.value) ? "correct" : "incorrect");
    input.addEventListener("input", () => {
      const current = currentAttempt();
      current.answers = { ...current.answers, [question.id]: input.value };
      current.submitted = false;
      current.completed = false;
      current.score = null;
      current.updatedAt = new Date().toISOString();
      persistAttempts();
      renderListeningProgress(item);
    });
    label.append(input);
    task.append(label);

    if (submitted) {
      const explanation = document.createElement("p");
      const review = listeningQuestionReview(question);
      explanation.className = `listening-explanation ${listeningAnswerCorrect(question, input.value) ? "" : "needs-review"}`;
      explanation.innerHTML = `<strong>正确答案：${escapeHtml(acceptedAnswerLabel(question))}</strong><span>${escapeHtml(review.evidenceLabel)}：${escapeHtml(review.evidence)}</span>${review.translation ? `<span>句意：${escapeHtml(review.translation)}</span>` : ""}<span>解析：${escapeHtml(review.explanation)}</span>`;
      task.append(explanation);
    }
  }

  const progress = document.createElement("p");
  progress.className = "answer-feedback";
  progress.dataset.listeningProgress = "";
  progress.textContent = submitted
    ? `本组 ${correct}/${item.questions.length} 正确。错误项已进入听力错题本。`
    : `${answered}/${item.questions.length} 已填写。提交前不会显示正误。`;
  task.append(progress);

  if (submitted) {
    const result = document.createElement("article");
    const evidenceCount = item.questions.filter((question) => hasReliableEvidence(question.evidence)).length;
    result.className = "listening-result";
    result.innerHTML = `<div><span>本次成绩</span><strong>${correct}/${item.questions.length}</strong><p>${evidenceCount === item.questions.length ? "逐题定位句与解析已展开。" : `已核对答案；${evidenceCount} 题含定位句，其余请结合原题面复核。`}</p></div><button type="button">再练一次</button>`;
    result.querySelector("button").addEventListener("click", () => {
      resetListeningAttempt();
      renderListening();
      renderPractice();
      showToast("已重置本组听力，可以重新作答。");
    });
    task.append(result);
  }

  const submit = document.createElement("button");
  submit.type = "button";
  submit.textContent = submitted ? "已提交" : "提交并查看结果";
  submit.disabled = submitted || answered !== item.questions.length;
  submit.addEventListener("click", () => submitListeningAttempt(item));
  task.append(submit);
  renderModuleCoachReview("Listening");
}

function renderListeningMode() {
  document.querySelectorAll("[data-listening-mode]").forEach((button) => {
    const selected = button.dataset.listeningMode === state.listeningMode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-listening-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.listeningPanel !== state.listeningMode;
  });
  const item = activeListeningItem();
  renderPracticeStep("listening", state.listeningMode === "study" ? "精听" : "答题", item?.title, state.listeningMode === "study" ? "先播放完整音频，再逐句听写。" : "填写全部答案后，提交查看成绩与解析。", state.listeningMode === "study" ? "播放音频" : "查看题目");
  const primary = document.querySelector('[data-practice-primary="listening"]');
  if (primary) primary.hidden = state.listeningMode === "study" && Boolean(item?.audioFile);
}

function listeningSentences(item) {
  const english = String(item.audioScript || "").match(/[^.!?]+[.!?]+|[^.!?]+$/g)?.map((sentence) => sentence.trim()).filter(Boolean) || [];
  const translated = String(item.audioScriptTranslation || "").match(/[^。！？]+[。！？]+|[^。！？]+$/g)?.map((sentence) => sentence.trim()).filter(Boolean) || [];
  return english.map((text, index) => ({ text, translation: translated[index] || "" }));
}

function renderListeningSentence(item) {
  const sentences = listeningSentences(item);
  if (!sentences.length) return;
  state.listeningSentenceIndex = Math.min(state.listeningSentenceIndex, sentences.length - 1);
  const sentence = sentences[state.listeningSentenceIndex];
  const attempt = currentAttempt();
  attempt.dictationAppearances ||= {};
  attempt.dictationAppearances[state.listeningSentenceIndex] ||= IELTSLearning.beginAppearance(sentence.text, `dictation:${state.activePracticeId}-${Date.now().toString(36)}-${++wordAppearanceSerial}:${state.listeningSentenceIndex}`);
  setText("[data-listening-sentence-count]", `${state.listeningSentenceIndex + 1} / ${sentences.length}`);
  setText("[data-listening-sentence-text]", state.listeningTranscriptVisible ? sentence.text : "原文已隐藏 · 先听写，再按上方“显示原文”核对");
  setText("[data-listening-sentence-translation]", sentence.translation);
  const translation = document.querySelector("[data-listening-sentence-translation]");
  if (translation) translation.hidden = !state.listeningTranslationVisible || !sentence.translation;
  const input = document.querySelector("[data-listening-dictation]");
  if (input) input.value = attempt?.dictation?.[state.listeningSentenceIndex] || "";
  const result = attempt?.dictationResults?.[state.listeningSentenceIndex];
  setText("[data-listening-dictation-result]", result || "核对后会标出遗漏词，并加入错题复习。");
  const loop = document.querySelector("[data-listening-loop]");
  if (loop) {
    loop.classList.toggle("active", state.listeningSentenceLoop);
    loop.setAttribute("aria-pressed", String(state.listeningSentenceLoop));
  }
  document.querySelectorAll("[data-listening-rate]").forEach((button) => button.classList.toggle("active", Number(button.dataset.listeningRate) === state.listeningSentenceRate));
}

function playListeningSentence() {
  const item = activeListeningItem();
  const sentence = listeningSentences(item)[state.listeningSentenceIndex];
  if (!sentence || !("speechSynthesis" in window)) return showToast("当前设备不支持逐句播放。");
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(sentence.text);
  utterance.lang = "en-US";
  utterance.rate = state.listeningSentenceRate;
  utterance.onend = () => {
    if (state.listeningSentenceLoop && document.querySelector('.screen[data-screen="listening"]')?.classList.contains("active")) playListeningSentence();
  };
  window.speechSynthesis.speak(utterance);
}

function checkListeningDictation() {
  const item = activeListeningItem();
  const sentence = listeningSentences(item)[state.listeningSentenceIndex];
  const input = document.querySelector("[data-listening-dictation]")?.value.trim() || "";
  if (!sentence || !input) return setText("[data-listening-dictation-result]", "请先输入你听到的内容。");
  const words = (text) => String(text).toLowerCase().match(/[a-z0-9]+/g) || [];
  const expected = words(sentence.text);
  const actual = words(input);
  const matched = expected.filter((word, index) => actual[index] === word).length;
  const accuracy = Math.round(matched / Math.max(1, expected.length) * 100);
  const missing = [...new Set(expected.filter((word) => !actual.includes(word)))].slice(0, 6);
  const attempt = currentAttempt();
  attempt.dictationAppearances ||= {};
  const appearance = attempt.dictationAppearances[state.listeningSentenceIndex];
  const hinted = Boolean(attempt?.dictationHints?.[state.listeningSentenceIndex]);
  const message = accuracy === 100
    ? hinted ? "文字正确，但已查看原文或翻译；本句仍加入复练。" : "完全正确。继续下一句。"
    : `准确率 ${accuracy}%${hinted ? " · 已使用提示" : ""} · 留意：${missing.join(" / ") || "词序与拼写"}`;
  attempt.dictation = { ...(attempt.dictation || {}), [state.listeningSentenceIndex]: input };
  attempt.dictationResults = { ...(attempt.dictationResults || {}), [state.listeningSentenceIndex]: message };
  attempt.updatedAt = new Date().toISOString();
  attempt.dictationProgress ||= {};
  attempt.dictationProgress[state.listeningSentenceIndex] = accuracy === 100 && !hinted
    ? IELTSLearning.recordSuccess(attempt.dictationProgress[state.listeningSentenceIndex], appearance, localIsoDate())
    : IELTSLearning.recordFailure(attempt.dictationProgress[state.listeningSentenceIndex], appearance, localIsoDate());
  if (!persistAttempts()) return setText("[data-listening-dictation-result]", "听写结果未能保存，请释放存储空间后重试。");
  if (accuracy < 100 || hinted) addWrongQuestion({
    id: `dictation-${item.id}-${state.listeningSentenceIndex}`,
    module: "Listening",
    sourceMaterial: `${item.title} · Sentence ${state.listeningSentenceIndex + 1}`,
    title: "逐句听写",
    userAnswer: input,
    correctAnswer: sentence.text,
    evidence: sentence.text,
    mistakeType: hinted && accuracy === 100 ? "listening-assisted" : "spelling",
    aiExplanation: message,
    reviewPoints: [{ label: hinted ? "提示记录" : "遗漏词", value: hinted ? "本轮核对前查看过原文或翻译" : missing.join(" / ") || "检查词序与拼写" }, { label: "原句", value: sentence.text }],
    nextReviewDate: tomorrowIsoDate(),
    createdAt: new Date().toISOString(),
    status: "待复盘",
  });
  setText("[data-listening-dictation-result]", message);
}

function renderNativeAudioPlayer(item) {
  const container = document.querySelector("[data-native-audio-player]");
  const fallbackButton = document.querySelector("[data-listening-play]");
  if (!container) return;

  if (!item.audioFile) {
    container.hidden = true;
    if (fallbackButton) {
      fallbackButton.hidden = false;
      fallbackButton.textContent = "▶ 播放系统朗读";
    }
    return;
  }

  if (fallbackButton) fallbackButton.hidden = true;
  container.hidden = false;
  container.innerHTML = `
    <span>${escapeHtml(item.audioLabel || "听力音频")}</span>
    <audio controls preload="metadata" src="${escapeHtml(item.audioFile)}"></audio>
    <div class="audio-speed" aria-label="播放速度">
      <button type="button" data-audio-rate="0.75">0.75×</button>
      <button type="button" class="active" data-audio-rate="1">1×</button>
      <button type="button" data-audio-rate="1.25">1.25×</button>
    </div>
    <button type="button" class="audio-download" data-media-download disabled>检查离线状态…</button>
    ${item.audioMatchesQuestions ? "" : '<p>此音频用于测试播放器，不对应下方四道功能样例题。</p>'}
  `;
  const audio = container.querySelector("audio");
  const download = container.querySelector("[data-media-download]");
  if ("caches" in window) caches.open(MEDIA_CACHE_NAME).then(async (cache) => {
    const downloaded = Boolean(await cache.match(item.audioFile));
    download.disabled = false;
    download.textContent = downloaded ? "删除离线音频" : "下载供离线使用";
  });
  download?.addEventListener("click", () => toggleMediaDownload(item.audioFile, item.audioLabel || item.title, download));
  audio.addEventListener("play", () => {
    const downloads = mediaDownloads();
    const saved = downloads.find((media) => media.url === item.audioFile);
    if (saved) {
      saved.lastUsed = new Date().toISOString();
      persistValue(MEDIA_DOWNLOADS_KEY, JSON.stringify(downloads));
    }
  });
  const restoreAudioTime = () => {
    const savedTime = Number(state.resumeState.audioTimes?.[state.activePracticeId] || 0);
    if (savedTime > 0 && savedTime < audio.duration) audio.currentTime = savedTime;
  };
  if (audio.readyState >= 1) restoreAudioTime();
  else audio.addEventListener("loadedmetadata", restoreAudioTime, { once: true });
  audio.addEventListener("pause", persistResumeState);
  container.querySelectorAll("[data-audio-rate]").forEach((button) => {
    button.addEventListener("click", () => {
      audio.playbackRate = Number(button.dataset.audioRate || 1);
      container.querySelectorAll("[data-audio-rate]").forEach((item) => item.classList.toggle("active", item === button));
      showToast(`播放速度：${button.textContent}`);
    });
  });
}

function renderListeningProgress(item) {
  const attempt = currentAttempt();
  const answered = item.questions.filter((question) => String(attempt?.answers?.[question.id] || "").trim()).length;
  setText("[data-listening-progress]", `${answered}/${item.questions.length} 已填写。提交前不会显示正误。`);
  const submit = document.querySelector("[data-listening-task] > button:last-child");
  if (submit) submit.disabled = answered !== item.questions.length;
}

function listeningAnswerCorrect(question, value, item = activeListeningItem(), answers = currentAttempt()?.answers || {}) {
  return aliasAnswerCorrect(question, value, item?.questions || [], answers);
}

async function submitListeningAttempt(item) {
  const attempt = currentAttempt();
  if (!attempt) return;
  const correct = item.questions.filter((question) => listeningAnswerCorrect(question, attempt.answers?.[question.id])).length;
  attempt.submitted = true;
  attempt.completed = true;
  attempt.score = `${correct}/${item.questions.length}`;
  attempt.updatedAt = new Date().toISOString();
  attempt.submittedAt = attempt.updatedAt;

  for (const question of item.questions) {
    const userAnswer = attempt.answers?.[question.id] || "未作答";
    if (listeningAnswerCorrect(question, userAnswer)) continue;
    const review = listeningQuestionReview(question);
    addWrongQuestion({
      id: `${state.activePracticeId}-${question.id}`,
      module: "Listening",
      sourceMaterial: `${item.source} · Question ${question.number}`,
      title: objectiveQuestionType("Listening", item, question),
      userAnswer,
      userAnswerLabel: userAnswer,
      correctAnswer: question.answer,
      correctAnswerLabel: acceptedAnswerLabel(question),
      mistakeType: "listening-gap-fill",
      status: "待复盘",
      evidence: review.evidence,
      aiExplanation: review.explanation,
      reviewPoints: [
        { label: review.evidenceLabel, value: review.evidence },
        ...(review.translation ? [{ label: "定位句意", value: review.translation }] : []),
        { label: "下次提醒", value: "播放前预测词性，听到定位词后留意答案前后的重读信息。" },
      ],
      nextReviewDate: tomorrowIsoDate(),
      createdAt: new Date().toISOString(),
    });
  }
  persistAttempts();
  trackLearningEvent({ module: "Listening", activity: item.title, durationMinutes: 12, score: correct, maxScore: item.questions.length, sourceId: state.activePracticeId, evidenceType: "objective" });
  markAssessmentModule("Listening", state.activePracticeId);
  renderListening();
  renderPractice();
  renderToday();
  trainingDebrief("Listening", correct, item.questions.length, 12);
  showToast(`听力已提交：${attempt.score}。错题已进入复习队列。`);
  showModuleCoachPending("Listening");
  try {
    const mistakes = item.questions.filter((question) => !listeningAnswerCorrect(question, attempt.answers?.[question.id])).map((question) => {
      const review = listeningQuestionReview(question);
      return { question: question.prompt, userAnswer: attempt.answers?.[question.id] || "未作答", correctAnswer: question.answer, evidence: review.evidence, explanation: review.explanation };
    });
    const aiText = await requestAI("listening_review", { exercise: { title: item.title, meta: item.meta }, result: { correct, total: item.questions.length }, mistakes });
    if (aiText) {
      rememberModuleReview("Listening", aiText, { sourceId: state.activePracticeId, score: `${correct}/${item.questions.length}`, mistakes: mistakes.length });
      showToast("AI 听力教练已根据本次错题生成复盘。", "success");
    }
  } catch (error) {
    showToast("听力成绩已保存，AI 复盘暂时不可用。", "error");
  } finally {
    renderModuleCoachReview("Listening");
  }
}

function resetListeningAttempt() {
  state.attempts[state.activePracticeId] = {
    answers: {}, completed: false, submitted: false, score: null,
    updatedAt: new Date().toISOString(), submittedAt: null,
  };
  persistAttempts();
}

function readingProgress(passage) {
  const attempt = currentAttempt();
  state.readingAnswers = attempt?.answers || state.readingAnswers;
  const answered = (passage.questions || []).filter((question) => state.readingAnswers[question.id]).length;
  return { answered, total: passage.questions?.length || 0 };
}

function readingAnswerCorrect(question, value, passage = activePassage(), answers = state.readingAnswers) {
  if (question.options) return Boolean(question.options.find((option) => option.id === value)?.correct);
  return aliasAnswerCorrect(question, value, passage?.questions || [], answers);
}

function scoreReadingAttempt(passage) {
  const correct = (passage.questions || []).filter((question) => readingAnswerCorrect(question, state.readingAnswers[question.id])).length;
  return `${correct}/${passage.questions?.length || 0}`;
}

function readingAttemptStats(passage) {
  const attempt = currentAttempt();
  const questions = passage.questions || [];
  const correct = questions.filter((question) => readingAnswerCorrect(question, state.readingAnswers[question.id])).length;
  const hintedCorrect = questions.filter((question) => attempt?.hints?.[question.id] && readingAnswerCorrect(question, state.readingAnswers[question.id])).length;
  return { correct, hintedCorrect, independentCorrect: Math.max(0, correct - hintedCorrect), total: questions.length };
}

function readingQuestionReview(question) {
  const evidenceReady = hasReliableEvidence(question.evidence);
  const source = question.evidence || "本地答案表";
  return {
    evidenceReady,
    evidenceLabel: evidenceReady ? "证据" : "来源",
    evidence: source,
    translation: String(question.evidenceTranslation || "").trim(),
    synonyms: evidenceReady
      ? String(question.synonyms || "").trim() || readingSynonymHints(source).join("；") || "本题暂未匹配到个人同义词库"
      : "本地尚未录入可核验定位句，暂不生成同义替换。",
    explanation: hasDetailedExplanation(question.aiExplanation)
      ? question.aiExplanation
      : "本地尚未录入逐题错因解析；请结合原题面与答案复核。",
  };
}

function readingEvidenceParagraph(passage, evidence) {
  return passage.paragraphs.find((paragraph) => paragraph.text.includes(evidence) || evidence.includes(paragraph.text)) || passage.paragraphs.find((paragraph) => evidence.split(/\s+/).filter((word) => word.length > 5).some((word) => paragraph.text.includes(word)));
}

function readingFocusSentence(paragraph) {
  return (paragraph.text.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [paragraph.text]).map((sentence) => sentence.trim()).sort((a, b) => b.length - a.length)[0];
}

function readingClauseBreakdown(text) {
  return String(text).split(/(?<=,)|\b(?=while|if|before|after|because|although|whether|that|which|who)\b/i).map((part) => part.trim()).filter(Boolean);
}

function readingSynonymHints(text) {
  const normalized = String(text || "").toLowerCase();
  return (state.synonyms?.groups || [])
    .filter((group) => group.terms.some((term) => new RegExp(`\\b${escapeRegExp(term)}\\b`, "i").test(normalized)))
    .slice(0, 2)
    .map((group) => group.terms.slice(0, 6).join(" ≈ "));
}

function toggleReadingTimer() {
  const button = document.querySelector("[data-reading-timer]");
  if (state.readingTimerId) {
    clearInterval(state.readingTimerId);
    state.readingTimerId = null;
    if (button) button.firstChild.textContent = "继续计时 · ";
    return;
  }
  state.readingStartedAt = Date.now() - state.readingElapsedSeconds * 1000;
  if (button) button.firstChild.textContent = "暂停计时 · ";
  state.readingTimerId = setInterval(() => {
    state.readingElapsedSeconds = Math.floor((Date.now() - state.readingStartedAt) / 1000);
    setText("[data-reading-time]", speakingDuration(state.readingElapsedSeconds));
  }, 1000);
}

function saveReadingSentence(passage, paragraph) {
  const text = readingFocusSentence(paragraph);
  const saved = { id: `reading-${passage.id}-${paragraph.id}`, text, source: `${passage.title} · Paragraph ${paragraph.id}`, savedAt: new Date().toISOString() };
  const index = state.savedSentences.findIndex((item) => item.id === saved.id);
  const previous = [...state.savedSentences];
  if (index >= 0) state.savedSentences[index] = saved;
  else state.savedSentences.unshift(saved);
  if (!persistValue(SAVED_SENTENCES_KEY, JSON.stringify(state.savedSentences))) {
    state.savedSentences = previous;
    return showToast("长句未能收藏，请释放存储空间后重试。", "error");
  }
  showToast("长句已收藏，可用于后续复述和写作素材。");
  renderReading();
}

async function submitReadingAttempt(passage) {
  const attempt = currentAttempt();
  if (!attempt) return;
  attempt.answers = { ...state.readingAnswers };
  attempt.submitted = true;
  attempt.completed = true;
  attempt.score = scoreReadingAttempt(passage);
  attempt.updatedAt = new Date().toISOString();
  attempt.submittedAt = attempt.updatedAt;

  for (const question of passage.questions || []) {
    const answer = state.readingAnswers[question.id];
    if (!answer) continue;
    const selected = question.options?.find((option) => option.id === answer) || { id: answer, label: answer, feedback: "请重新核对原题与答案。" };
    if (!readingAnswerCorrect(question, answer)) {
      addWrongQuestion(createReadingWrongQuestion(passage, question, selected));
      continue;
    }
    if (attempt.hints?.[question.id]) {
      const assisted = createReadingWrongQuestion(passage, question, selected);
      assisted.mistakeType = "reading-assisted";
      assisted.aiExplanation = "本题答案正确，但作答过程中查看过定位提示；已加入复练，下一次先独立定位。";
      assisted.reviewPoints = [
        { label: "提示记录", value: "本轮查看过定位句" },
        { label: "下次提醒", value: "先圈题干关键词并独立定位，再核对提示。" },
      ];
      addWrongQuestion(assisted);
    }
  }
  persistAttempts();
  const { correct, hintedCorrect, independentCorrect, total } = readingAttemptStats(passage);
  attempt.independentScore = `${independentCorrect}/${total}`;
  attempt.hintCount = Object.keys(attempt.hints || {}).length;
  persistAttempts();
  if (state.readingTimerId) clearInterval(state.readingTimerId);
  state.readingTimerId = null;
  const durationMinutes = Math.max(1, Math.round(state.readingElapsedSeconds / 60) || 18);
  trackLearningEvent({ module: "Reading", activity: passage.title, durationMinutes, score: independentCorrect, maxScore: total, sourceId: state.activePracticeId, evidenceType: "objective" });
  markAssessmentModule("Reading", state.activePracticeId);
  state.readingReviewVisible = true;
  state.readingMode = "review";
  state.examMode = false;
  renderToday();
  trainingDebrief("Reading", independentCorrect, total, durationMinutes);
  showModuleCoachPending("Reading");
  try {
    const questions = (passage.questions || []).map((question) => {
      const answer = state.readingAnswers[question.id];
      const selected = question.options?.find((option) => option.id === answer);
      const correctOption = question.options?.find((option) => option.correct);
      return { prompt: question.prompt, userAnswer: selected?.label || answer || "未作答", correctAnswer: correctOption?.label || acceptedAnswerLabel(question), correct: readingAnswerCorrect(question, answer), usedHint: Boolean(attempt.hints?.[question.id]), evidence: question.evidence || "" };
    });
    const aiText = await requestAI("reading_review", { passage: { title: passage.title, summary: passage.summary }, result: { correct, independentCorrect, total, hintCount: attempt.hintCount }, questions });
    if (aiText) {
      rememberModuleReview("Reading", aiText, { sourceId: state.activePracticeId, score: `${independentCorrect}/${total}`, hints: attempt.hintCount });
      showToast("AI 阅读教练已结合答案与定位证据生成复盘。", "success");
    }
  } catch (error) {
    showToast("阅读成绩已保存，AI 复盘暂时不可用。", "error");
  } finally {
    renderModuleCoachReview("Reading");
  }
}

function resetReadingAttempt() {
  if (state.readingTimerId) clearInterval(state.readingTimerId);
  state.readingTimerId = null;
  state.readingStartedAt = null;
  state.readingElapsedSeconds = 0;
  state.attempts[state.activePracticeId] = {
    answers: {}, hints: {}, completed: false, submitted: false, score: null, independentScore: null,
    updatedAt: new Date().toISOString(), submittedAt: null,
  };
  state.readingAnswers = {};
  state.readingReviewVisible = false;
  state.readingFocusParagraphId = null;
  state.readingFocusQuestionId = null;
  state.readingMode = "article";
  state.examMode = false;
  persistAttempts();
}

function resetReadingTransientContext() {
  if (state.readingTimerId) clearInterval(state.readingTimerId);
  state.readingTimerId = null;
  state.readingStartedAt = null;
  state.readingElapsedSeconds = 0;
  state.readingFocusParagraphId = null;
  state.readingFocusQuestionId = null;
  state.readingBreakdownParagraphId = null;
  state.translationVisible = false;
  state.readingReviewVisible = false;
}

function selectedAnswerText(question, selectedId) {
  if (!selectedId) return "填写答案后再提交；提交前不会显示正误。";
  const selected = question.options?.find((option) => option.id === selectedId);
  return `已填写：${selected?.label || selectedId}。提交前可以修改。`;
}

function renderReadingReview(passage) {
  const review = document.createElement("article");
  review.className = "reading-review";
  review.innerHTML = `
    <span>解析复盘</span>
    <h3>答案与可用复盘依据</h3>
    ${(passage.questions || [])
      .map((question) => {
        const selected = state.readingAnswers[question.id];
        const correct = question.options?.find((option) => option.correct);
        const chosen = question.options?.find((option) => option.id === selected);
        const correctLabel = correct?.label || acceptedAnswerLabel(question);
        const chosenLabel = chosen?.label || selected || "未作答";
        const wrong = Boolean(selected && !readingAnswerCorrect(question, selected));
        const assisted = Boolean(currentAttempt()?.hints?.[question.id] && !wrong);
        const review = readingQuestionReview(question);
        const stepOffset = review.translation ? 1 : 0;
        const promptReady = question.prompt && !/请参考原题面/.test(question.prompt);
        return `
          <div class="review-answer ${wrong ? "needs-review" : assisted ? "assisted" : ""}">
            <strong>${escapeHtml(question.label)} · ${escapeHtml(correctLabel)}</strong>
            ${promptReady ? `<p class="review-question-prompt"><b>题干</b> ${escapeHtml(question.prompt)}</p>` : ""}
            <p><b>01 / 答案</b> 你的答案：${escapeHtml(chosenLabel)}${assisted ? "（使用过定位提示）" : ""}</p>
            <p><b>02 / ${escapeHtml(review.evidenceLabel)}</b> ${escapeHtml(review.evidence)}</p>
            ${review.translation ? `<p><b>03 / 句意</b> ${escapeHtml(review.translation)}</p>` : ""}
            <p><b>0${3 + stepOffset} / 同义</b> ${escapeHtml(review.synonyms)}</p>
            <p><b>0${4 + stepOffset} / 复盘</b> ${escapeHtml(assisted ? `答案正确，但本轮使用过定位提示；下次先独立定位。${review.explanation}` : wrong ? hasDetailedExplanation(chosen?.feedback) ? chosen.feedback : review.explanation : `本题独立完成。${review.explanation}`)}</p>
          </div>
        `;
      })
      .join("")}
  `;
  return review;
}

function renderReadingPersonalSource(passage) {
  renderPersonalSource({ selector: "[data-reading-personal-source]", map: "readingSourceMap", key: READING_SOURCE_MAP_KEY, item: passage, title: "个人阅读资料", label: "可选", selectLabel: "关联本篇", description: { selected: "先看资料，再回到本页完成定位与摘要。", empty: "选择个人练习或解析资料作为补充来源；不会改变本地题目与答案。" }, empty: "未找到可直接预览的阅读资料。", candidates: personalSourceCandidates("reading", ["preview"], /练习|解析|同义词|判断题|heading|匹配/i), rerender: renderReading });
}

function renderReading() {
  const passage = activePassage();
  if (!passage) return;
  const quality = contentQuality("Reading", passage.source);
  const attempt = currentAttempt();
  const submitted = Boolean(attempt?.submitted || (attempt?.completed && attempt?.score));
  document.querySelector(".screen[data-screen='reading']")?.classList.toggle("exam-mode", state.examMode);

  setText("[data-reading-source]", state.examMode ? `${passage.source} · Exam mode · 18:00` : passage.source);
  setText("[data-reading-title]", passage.title);
  setText("[data-reading-summary]", state.examMode ? "考试模式：隐藏翻译和点词，提交后统一查看解析。" : passage.summary);
  const sourceMap = state.readingSourceMap[passage.id];
  const teachingStatus = passage.teachingReview?.status === "human-reviewed" ? " · 逐题人工精校" : "";
  setText("[data-reading-rights]", passage.sourcePages ? `个人 iCloud 来源 · ${quality.label}${teachingStatus} · ${sourceMap ? "已关联个人补充资料 · " : ""}原文 p.${passage.sourcePages.passage.join("-")} · 题面 p.${passage.sourcePages.questions} · 答案 p.${passage.sourcePages.answers}` : "本地学习样本");
  renderReadingPersonalSource(passage);
  setText("[data-reading-time]", speakingDuration(state.readingElapsedSeconds));

  const body = document.querySelector("[data-reading-body]");
  if (body) {
    const focusQuestion = (passage.questions || []).find((question) => question.id === state.readingFocusQuestionId);
    body.replaceChildren(
      ...passage.paragraphs.map((paragraph) => {
        const card = document.createElement("article");
        card.className = `reading-card ${state.readingFocusParagraphId === paragraph.id ? "is-evidence" : ""}`;
        card.dataset.readingParagraph = paragraph.id;
        const focusSentence = readingFocusSentence(paragraph);
        const saved = state.savedSentences.some((item) => item.id === `reading-${passage.id}-${paragraph.id}`);
        card.innerHTML = `
          <span class="paragraph-label">Paragraph ${escapeHtml(paragraph.id)}</span>
          ${state.readingFocusParagraphId === paragraph.id && focusQuestion ? `<aside class="reading-evidence-handoff"><span>${escapeHtml(focusQuestion.label)} 已使用定位提示</span><button type="button" data-reading-return>回到题目</button></aside>` : ""}
          <p>${state.examMode ? escapeHtml(paragraph.text) : renderClickableParagraph(paragraph)}</p>
          <p class="paragraph-translation" ${state.translationVisible && !state.examMode ? "" : "hidden"}>${escapeHtml(paragraph.translation || "")}</p>
          <div class="reading-paragraph-actions" ${state.examMode ? "hidden" : ""}>
            <button data-reading-save>${saved ? "已收藏" : "收藏长句"}</button>
            <button data-reading-breakdown>${state.readingBreakdownParagraphId === paragraph.id ? "收起拆解" : "长难句拆解"}</button>
          </div>
          ${state.readingBreakdownParagraphId === paragraph.id && !state.examMode ? `<div class="sentence-breakdown"><span>LONG SENTENCE</span>${readingClauseBreakdown(focusSentence).map((clause, index) => `<p><b>0${index + 1}</b>${escapeHtml(clause)}</p>`).join("")}</div>` : ""}
        `;
        card.querySelector("[data-reading-save]")?.addEventListener("click", () => saveReadingSentence(passage, paragraph));
        card.querySelector("[data-reading-return]")?.addEventListener("click", () => {
          state.readingMode = "questions";
          renderReading();
          document.querySelector(`[data-reading-question="${focusQuestion?.id || ""}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
        card.querySelector("[data-reading-breakdown]")?.addEventListener("click", () => {
          state.readingBreakdownParagraphId = state.readingBreakdownParagraphId === paragraph.id ? null : paragraph.id;
          renderReading();
        });
        return card;
      })
    );
  }

  const translationToggle = document.querySelector("[data-toggle-translation]");
  if (translationToggle) {
    const translationReady = passage.paragraphs.some((paragraph) => String(paragraph.translation || "").trim());
    if (!translationReady) state.translationVisible = false;
    translationToggle.textContent = translationReady ? (state.translationVisible ? "隐藏翻译" : "全文翻译") : "暂无全文翻译";
    translationToggle.disabled = state.examMode || !translationReady;
  }
  const examToggle = document.querySelector("[data-exam-mode]");
  if (examToggle) examToggle.textContent = state.examMode ? "学习模式" : "考试模式";

  const questionList = document.querySelector("[data-reading-questions]");
  if (questionList) {
    const { answered, total } = readingProgress(passage);
    const progress = document.createElement("article");
    progress.className = "reading-progress";
    progress.innerHTML = `
      <strong>${answered}/${total} 已完成</strong>
      <span>${state.examMode ? "考试模式：完成后提交" : answered === total ? "可以提交并查看复盘" : "完成全部题目后解锁复盘"}</span>
    `;

    const reviewButton = document.createElement("button");
    reviewButton.className = "primary-action reading-review-action";
    reviewButton.textContent = submitted
      ? "查看解析"
      : state.examMode ? "提交试卷" : "提交并查看结果";
    reviewButton.disabled = answered !== total;
    reviewButton.addEventListener("click", () => {
      if (!submitted) {
        submitReadingAttempt(passage);
        const stats = readingAttemptStats(passage);
        showToast(stats.hintedCorrect
          ? `原始正确 ${stats.correct}/${stats.total}；独立完成 ${stats.independentCorrect}/${stats.total}，提示题已加入复练。`
          : `已提交，本次独立完成 ${stats.correct}/${stats.total}。错题已进入复习队列。`);
      } else {
        state.readingMode = "review";
      }
      renderReading();
      renderPractice();
    });

    const result = document.createElement("article");
    const resultStats = readingAttemptStats(passage);
    const evidenceCount = (passage.questions || []).filter((question) => hasReliableEvidence(question.evidence)).length;
    result.className = "reading-result";
    result.innerHTML = `
      <div><span>本次成绩</span><strong>${escapeHtml(attempt?.score || "-")}</strong><p>${resultStats.hintedCorrect ? `独立完成 ${resultStats.independentCorrect}/${resultStats.total} · ${resultStats.hintedCorrect} 题使用提示。` : `已核对答案；${evidenceCount} 题含可核验定位句。`}</p></div>
      <button type="button">再练一次</button>
    `;
    result.querySelector("button").addEventListener("click", () => {
      resetReadingAttempt();
      renderReading();
      renderPractice();
      showToast("已重置本篇练习，可以重新作答。");
    });

    const paper = document.createElement("details");
    paper.className = "reading-paper";
    paper.open = true;
    paper.innerHTML = "<summary>查看原题面</summary><pre></pre>";
    paper.querySelector("pre").textContent = passage.questionPaper || "";

    questionList.replaceChildren(
      progress,
      ...(passage.questionPaper ? [paper] : []),
      ...(passage.questions || []).map((question) => {
        const card = document.createElement("article");
        card.className = "reading-task";
        card.dataset.readingQuestion = question.id;
        const options = document.createElement("div");
        options.className = "answer-list";

        const feedback = document.createElement("p");
        feedback.className = "answer-feedback";
        feedback.textContent = "选择一个答案后，这里会显示解析；答错会自动进入错题本。";

        if (question.options) options.replaceChildren(
          ...question.options.map((option) => {
            const button = document.createElement("button");
            button.textContent = option.label;
            const selected = state.readingAnswers[question.id] === option.id;
            button.classList.toggle("selected", selected);
            button.classList.toggle("correct", submitted && selected && Boolean(option.correct));
            button.classList.toggle("incorrect", submitted && selected && !option.correct);
            button.disabled = submitted;
            button.addEventListener("click", () => {
              state.readingAnswers[question.id] = option.id;
              const attempt = currentAttempt();
              if (attempt) {
                attempt.answers = { ...state.readingAnswers };
                attempt.updatedAt = new Date().toISOString();
                attempt.completed = false;
                attempt.submitted = false;
                attempt.score = null;
                persistAttempts();
              }
              showToast(`${question.label} 已选择 ${option.id}，提交前可以修改。`);
              renderReading();
            });
            return button;
          })
        );
        else {
          const input = document.createElement("input");
          input.className = "reading-text-answer";
          input.value = state.readingAnswers[question.id] || "";
          input.placeholder = "输入答案或选项字母";
          input.disabled = submitted;
          input.classList.toggle("correct", submitted && readingAnswerCorrect(question, input.value));
          input.classList.toggle("incorrect", submitted && !readingAnswerCorrect(question, input.value));
          input.addEventListener("input", () => {
            state.readingAnswers[question.id] = input.value;
            const attempt = currentAttempt();
            if (attempt) {
              attempt.answers = { ...state.readingAnswers };
              attempt.updatedAt = new Date().toISOString();
              attempt.completed = false;
              attempt.submitted = false;
              attempt.score = null;
              persistAttempts();
            }
            const status = readingProgress(passage);
            progress.querySelector("strong").textContent = `${status.answered}/${status.total} 已完成`;
            progress.querySelector("span").textContent = status.answered === status.total ? "可以提交并查看完整解析" : "完成全部题目后解锁解析";
            reviewButton.disabled = status.answered !== status.total;
          });
          options.append(input);
        }

        card.innerHTML = `
          <span>${escapeHtml(question.label)} · ${escapeHtml(question.type)}</span>
          <h3>${escapeHtml(question.prompt)}</h3>
        `;
        if (submitted) {
          const chosen = question.options?.find((option) => option.id === state.readingAnswers[question.id]);
          const assisted = Boolean(attempt?.hints?.[question.id] && readingAnswerCorrect(question, state.readingAnswers[question.id]));
          feedback.textContent = readingAnswerCorrect(question, state.readingAnswers[question.id])
            ? assisted ? "答案正确，但本轮使用过定位提示；已加入复练。" : chosen?.feedback || "回答正确。"
            : `${chosen?.feedback || "答案不正确。"} 正确答案：${question.options?.find((option) => option.correct)?.label || acceptedAnswerLabel(question) || "-"}`;
        } else {
          feedback.textContent = selectedAnswerText(question, state.readingAnswers[question.id]);
        }
        card.append(options, feedback);
        if (!submitted && !state.examMode && hasReliableEvidence(question.evidence)) {
          const locate = document.createElement("button");
          locate.className = "reading-locate";
          locate.textContent = attempt?.hints?.[question.id] ? "已看定位 · 返回原文" : "查看定位（计为提示）";
          locate.addEventListener("click", () => {
            const paragraph = readingEvidenceParagraph(passage, question.evidence || "");
            if (!paragraph) return showToast("这道题的定位句暂时无法对应到当前原文。", "error");
            attempt.hints = { ...(attempt.hints || {}), [question.id]: true };
            attempt.updatedAt = new Date().toISOString();
            persistAttempts();
            state.readingFocusParagraphId = paragraph.id;
            state.readingFocusQuestionId = question.id;
            state.readingMode = "article";
            renderReading();
            [...document.querySelectorAll("[data-reading-paragraph]")].find((element) => element.dataset.readingParagraph === state.readingFocusParagraphId)?.scrollIntoView({ behavior: "smooth", block: "center" });
          });
          card.append(locate);
        }
        return card;
      }),
      reviewButton
    );
    const reviewPanel = document.querySelector("[data-reading-review]");
    if (reviewPanel) reviewPanel.replaceChildren(...(submitted
      ? [result, renderReadingReview(passage)]
      : [Object.assign(document.createElement("article"), { className: "empty-state", innerHTML: '<strong>完成题目后查看复盘</strong><p>提交后会显示答案，以及本地已有的定位句和解析；缺失内容会明确标注。</p><button data-empty-go="reading" data-empty-mode="questions">去完成题目</button>' })]));
  }
  renderModuleCoachReview("Reading");
  renderReadingMode();
}

function renderReadingMode() {
  document.querySelectorAll("[data-reading-mode]").forEach((button) => {
    const selected = button.dataset.readingMode === state.readingMode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-reading-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.readingPanel !== state.readingMode;
  });
  const passage = activePassage();
  const submitted = Boolean(currentAttempt()?.submitted || (currentAttempt()?.completed && currentAttempt()?.score));
  const modes = {
    article: ["阅读", "先通读文章，可随时点词查义。", "开始答题"],
    questions: ["题目", "完成全部题目后，提交核对答案；查看定位会计为提示。", "继续答题"],
    review: ["解析", submitted ? "查看答案与本地已有解析；缺失内容会明确标注。" : "完成题目并提交后解锁复盘。", submitted ? "查看解析" : "去完成题目"],
  };
  renderPracticeStep("reading", modes[state.readingMode][0], passage?.title, modes[state.readingMode][1], modes[state.readingMode][2]);
}

function renderVocabBook() {
  const list = document.querySelector("[data-saved-word-list]");
  const count = document.querySelector("[data-vocab-count]");
  if (count) count.textContent = state.savedWords.length;
  if (!list) return;

  if (state.savedWords.length === 0) {
    list.innerHTML = `
      <article class="empty-state">
        <strong>还没有保存生词</strong>
        <p>去阅读页点一个不认识的词，然后加入生词本。</p>
        <button data-empty-go="reading" data-empty-mode="article">去阅读查词</button>
      </article>
    `;
    return;
  }

  list.replaceChildren(
    ...state.savedWords.map((item) => {
      const card = document.createElement("article");
      card.className = "saved-word-card";
      card.innerHTML = `
        <div>
          <strong>${item.word}</strong>
          <span>美音 ${item.phonetic}</span>
        </div>
        <button aria-label="播放 ${item.word} 美音">🔊</button>
        <p>${item.definition}</p>
        <small>${item.sourceSentence}</small>
      `;
      card.querySelector("button").addEventListener("click", () => speakWord(item.word));
      return card;
    })
  );
}

function renderWrongQuestions() {
  const allItems = state.userWrongQuestions;
  allItems.forEach((item) => { item.category = item.category || wrongTypeLabel(item.mistakeType); });
  renderWrongMasteryDashboard(allItems);
  renderWeakDrillPack(allItems);
  const moduleSelect = document.querySelector("[data-wrong-module]");
  const questionTypeSelect = document.querySelector("[data-wrong-question-type]");
  const typeSelect = document.querySelector("[data-wrong-type]");
  const modules = [...new Set(allItems.map((item) => item.module))];
  const questionTypes = [...new Set(allItems.map((item) => item.title).filter(Boolean))];
  const types = [...new Set(allItems.map((item) => item.category))];
  if (moduleSelect) {
    moduleSelect.innerHTML = `<option value="全部">全部模块</option>${modules.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(MODULE_LABELS[value] || value)}</option>`).join("")}`;
    moduleSelect.value = state.wrongModuleFilter;
  }
  if (typeSelect) {
    typeSelect.innerHTML = `<option value="全部">全部错因</option>${types.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
    typeSelect.value = state.wrongTypeFilter;
  }
  if (questionTypeSelect) {
    questionTypeSelect.innerHTML = `<option value="全部">全部题型</option>${questionTypes.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("")}`;
    questionTypeSelect.value = state.wrongQuestionTypeFilter;
  }
  const items = allItems.filter((item) => (state.wrongModuleFilter === "全部" || item.module === state.wrongModuleFilter)
    && (state.wrongQuestionTypeFilter === "全部" || item.title === state.wrongQuestionTypeFilter)
    && (state.wrongTypeFilter === "全部" || item.category === state.wrongTypeFilter));
  const dueItems = wrongReviewQueue(items);
  const pendingItems = wrongReviewQueue(allItems);
  const item = items.find((wrong) => wrong.id === state.activeWrongId) || dueItems[0] || items.find((wrong) => !isWrongMastered(wrong)) || items[0];
  const learningCount = allItems.filter((wrong) => !isWrongMastered(wrong)).length;
  const dueTomorrowCount = allItems.filter((wrong) => wrong.nextReviewDate === tomorrowIsoDate()).length;
  const pendingCount = pendingItems.length;
  setText(".graph-summary h2", pendingCount ? `${pendingCount} 道错题今天到期` : "今天的复盘已完成");
  setText("#saveStatus", pendingCount ? "先完成到期错题；每次评价掌握程度后，系统会安排下次复习。" : learningCount ? `还有 ${learningCount} 道错题在复习计划中，现在可以继续新练习。` : "完成练习后，错题会自动整理到这里。");

  const nextButton = document.querySelector("[data-wrong-next]");
  if (nextButton) {
    nextButton.textContent = pendingCount ? "开始下一道" : allItems.length ? "查看全部错题" : "去做练习";
    nextButton.onclick = () => {
      if (pendingItems[0]) {
        state.activeWrongId = pendingItems[0].id;
        state.wrongMode = "detail";
        renderWrongQuestions();
      } else if (allItems.length) {
        state.wrongMode = "library";
        renderWrongQuestions();
      } else {
        showScreen("practice");
      }
    };
  }

  const statValues = document.querySelectorAll("[data-wrong-stats] strong");
  if (statValues[0]) statValues[0].textContent = pendingCount;
  if (statValues[1]) statValues[1].textContent = learningCount;
  if (statValues[2]) statValues[2].textContent = dueTomorrowCount;
  const card = document.querySelector("[data-wrong-card]");
  const library = document.querySelector("[data-wrong-library]");
  if (library) library.replaceChildren(...(items.length ? items.map((wrong) => {
    const button = document.createElement("button");
    button.className = wrong.id === item?.id ? "selected" : "";
    button.innerHTML = `<span>${escapeHtml(MODULE_LABELS[wrong.module] || wrong.module)} · ${escapeHtml(wrong.category)}</span><strong>${escapeHtml(wrong.title || wrong.sourceMaterial)}</strong><em>${isWrongMastered(wrong) ? "已掌握" : isWrongDue(wrong) ? "今日到期" : `下次 ${escapeHtml(wrong.nextReviewDate || "待安排")}`}</em>`;
    button.addEventListener("click", () => {
      state.activeWrongId = wrong.id;
      state.wrongMode = "detail";
      renderWrongQuestions();
    });
    return button;
  }) : [Object.assign(document.createElement("p"), { textContent: "这个分类暂无错题。" })]));
  renderWrongMode();
  if (!item) {
    if (card) card.innerHTML = `<div class="empty-state"><strong>这个分类暂无错题</strong><p>清除筛选即可查看其他错题。</p><button data-empty-reset="wrong">清除筛选</button></div>`;
    document.querySelector("[data-review-points] .review-list")?.replaceChildren();
    return;
  }

  setText("[data-review-queue-count]", `${dueItems.length} 项`);
  const queue = document.querySelector("[data-review-queue]");
  if (queue) queue.replaceChildren(...(dueItems.length ? dueItems.slice(0, 5).map((wrong, index) => {
    const button = document.createElement("button");
    button.className = wrong.id === item.id ? "selected" : "";
    button.innerHTML = `<span>0${index + 1}</span><strong>${escapeHtml(MODULE_LABELS[wrong.module] || wrong.module)} · ${escapeHtml(wrong.category)}</strong><em>${Number(wrong.reviewStage || 0) === 0 ? "首次复盘" : `第 ${Number(wrong.reviewStage)} 阶段`}</em>`;
    button.addEventListener("click", () => {
      state.activeWrongId = wrong.id;
      state.wrongMode = "detail";
      renderWrongQuestions();
    });
    return button;
  }) : [Object.assign(document.createElement("p"), { textContent: "今天没有到期错题，可以继续新练习。" })]));

  if (card) {
    card.innerHTML = `
      <div class="wrong-card-top">
        <div>
          <span>${escapeHtml(MODULE_LABELS[item.module] || item.module)} · ${escapeHtml(item.category)}</span>
          <h3>${escapeHtml(item.sourceMaterial)}</h3>
        </div>
        <em>${isWrongMastered(item) ? "已掌握" : isWrongDue(item) ? "今日到期" : `下次 ${escapeHtml(item.nextReviewDate)}`}</em>
      </div>
      <p class="wrong-question">${escapeHtml(item.title)} · 你选 ${escapeHtml(item.userAnswerLabel || item.userAnswer)}，答案 ${escapeHtml(item.correctAnswerLabel || item.correctAnswer)}</p>
      <div class="wrong-reason">
        <strong>错因</strong>
        <p>${escapeHtml(item.aiExplanation)}</p>
      </div>
      <div class="wrong-card-actions">
        <button data-review-source>回到原题</button>
      </div>
      <div class="review-rating" aria-label="本次掌握程度">
        <span>这次记住了吗？</span>
        <div><button data-review-rating="again">忘记</button><button data-review-rating="hard">困难</button><button data-review-rating="good">记住</button><button data-review-rating="easy">简单</button></div>
      </div>
    `;
    card.querySelector("[data-review-source]")?.addEventListener("click", () => {
      if (item.module === "Listening") {
        state.activePracticeId = item.id.split("-q")[0];
        renderListening();
        showScreen("listening");
        showToast("已回到听力原题，重看答案、定位句和拼写。");
        return;
      }
      if (item.module === "Writing") {
        renderWriting();
        showScreen("writing");
        showToast("已回到写作任务，可按本条反馈修改下一稿。");
        return;
      }
      if (item.module === "Speaking") {
        state.activeSpeakingSessionId = item.sessionId || state.activeSpeakingSessionId;
        renderSpeakingCoach();
        showScreen("speaking");
        showToast("已回到口语教练，可回听并继续回答。");
        return;
      }
      const passageId = item.id.replace(/-q\d+$/, "");
      const readingTest = state.tests?.collections
        ?.flatMap((collection) => collection.items)
        .find((test) => test.sourceId === passageId);
      state.activePracticeId = readingTest?.id || "reading-demo-p1";
      state.readingAnswers = currentAttempt()?.answers || {};
      state.translationVisible = false;
      state.examMode = false;
      state.readingReviewVisible = true;
      renderReading();
      showScreen("reading");
      showToast("已回到原文，重看定位句和选项同义替换。");
    });
    card.querySelectorAll("[data-review-rating]").forEach((button) => button.addEventListener("click", () => rateWrongQuestion(item, button.dataset.reviewRating)));
  }

  const reviewList = document.querySelector("[data-review-points] .review-list");
  if (reviewList) {
    const points = item.reviewPoints?.length
      ? item.reviewPoints
      : [
          { label: "定位句", value: item.evidence },
          { label: "错因", value: item.aiExplanation },
          { label: "下次提醒", value: "复盘时先定位证据句，再看选项同义替换。" },
        ];
    reviewList.replaceChildren(
      ...points.map((point) => {
        const row = document.createElement("div");
        row.innerHTML = typeof point === "string"
          ? `<strong>复盘要点</strong><span>${escapeHtml(point)}</span>`
          : `<strong>${escapeHtml(point.label)}</strong><span>${escapeHtml(point.value)}</span>`;
        return row;
      })
    );
  }
}

function renderWrongMode() {
  document.querySelectorAll("[data-wrong-mode]").forEach((button) => {
    const selected = button.dataset.wrongMode === state.wrongMode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-wrong-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.wrongPanel !== state.wrongMode;
  });
}

function renderProfileDashboard() {
  const minutes = weeklyModuleMinutes();
  const scores = moduleBandScores();
  const totalMinutes = Object.values(minutes).reduce((sum, value) => sum + value, 0);
  const estimate = assessmentSnapshot();
  setText("[data-profile-streak]", `${learningStreak()}天`);
  setText("[data-profile-minutes]", `${Math.round(totalMinutes)}分`);
  setText("[data-profile-band]", estimate.band === null ? "—" : estimate.band.toFixed(1));
  setText("[data-band-overall]", estimate.band === null ? "—" : estimate.band.toFixed(1));

  const aiEndpoint = document.querySelector("[data-ai-endpoint]");
  if (aiEndpoint && !aiEndpoint.value) aiEndpoint.value = localStorage.getItem(AI_ENDPOINT_KEY) || "";
  renderLearnerProfile();
  renderContentStatus();
  renderLearningDashboard();
  renderDataHealth();
  renderStorageStatus();
  renderBackupStatus();
}

function renderAIAssistant() {
  const ready = aiServiceReady();
  const provider = aiProviderLabel();
  if (!ready && !configuredAIEndpoint()) autoConfigureAIEndpoint();
  setText("[data-ai-page-status]", ready
    ? `${provider} 已连接；听、说、读、写的复盘与计划共用同一份本地学习记忆。`
    : aiAutoConfiguring
      ? "正在自动连接本地 AI 服务…"
      : configuredAIEndpoint()
        ? "AI 地址待验证，当前使用本地规则。"
      : "AI 服务未连接；请先启动本地服务（npm run agent:radeon），或在 我的 → 学习服务 中验证地址。");
  renderAiMemory();
  renderSubjectCoaches();
  renderAiChat();
  renderAgentChat();
}

function renderModuleCoachReview(module) {
  const container = document.querySelector(`[data-module-coach-review="${module}"]`);
  if (!container) return;
  const review = latestModuleReview(module);
  container.hidden = !review || (module === "Listening" && state.listeningMode !== "test");
  if (!review) return;
  container.innerHTML = `<header><span>AI ${escapeHtml(MODULE_LABELS[module] || module)}教练</span><em>${new Date(review.createdAt).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</em></header><div>${renderAgentMarkdown(review.summary)}</div><button type="button" data-go="ai">结合四科记录调整计划</button>`;
  container.querySelector("[data-go='ai']")?.addEventListener("click", () => showScreen("ai"));
}

function showModuleCoachPending(module) {
  const container = document.querySelector(`[data-module-coach-review="${module}"]`);
  if (!container) return;
  container.hidden = false;
  container.innerHTML = `<header><span>AI ${escapeHtml(MODULE_LABELS[module] || module)}教练</span><em>分析中</em></header><div><p>正在读取本次作答、错题证据和长期学习记录…</p></div>`;
}

function openSubjectCoach(module) {
  if (module === "Listening") state.listeningMode = "test";
  if (module === "Reading") state.readingMode = "review";
  if (module === "Writing") state.writingMode = "feedback";
  const screen = ({ Listening: "listening", Reading: "reading", Writing: "writing", Speaking: "speaking" })[module];
  if (screen) showScreen(screen);
}

function renderSubjectCoaches() {
  const list = document.querySelector("[data-ai-subject-list]");
  if (!list) return;
  list.replaceChildren(...["Listening", "Reading", "Writing", "Speaking"].map((module) => {
    const review = latestModuleReview(module);
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.subjectCoach = module;
    button.innerHTML = `<span>${escapeHtml(module.toUpperCase())}</span><strong>${escapeHtml(MODULE_LABELS[module])}教练</strong><p>${review ? escapeHtml(review.summary.replace(/[#*_`]/g, "").replace(/\s+/g, " ").slice(0, 88)) : "完成一次练习后生成个人复盘"}</p><em>${review ? "已有记录" : "等待证据"}</em>`;
    button.addEventListener("click", () => openSubjectCoach(module));
    return button;
  }));
}

function renderAiMemory() {
  const snapshot = learningMemorySnapshot();
  const weak = snapshot.progress.weakModules[0];
  const latest = state.aiMemory.moduleReviews[0]?.summary || snapshot.speaking.latestDebrief?.summary || "";
  setText("[data-ai-memory-sessions]", String(snapshot.progress.aiReviews));
  setText("[data-ai-memory-evidence]", String(state.learningEvents.length + state.aiMemory.agentHistory.length + state.aiMemory.moduleReviews.length));
  setText("[data-ai-memory-reviews]", String(snapshot.progress.dueReviews));
  setText("[data-ai-memory-focus]", weak ? `${MODULE_LABELS[weak.module] || weak.module} · ${weak.count} 条近期薄弱证据` : "完成一次练习后形成个人能力画像");
  setText("[data-ai-memory-latest]", latest
    ? `最近复盘：${latest.replace(/[#*_`]/g, "").replace(/\s+/g, " ").slice(0, 96)}${latest.length > 96 ? "…" : ""}`
    : "AI 会把你的原话、错题和反馈用于下一次训练。");
}

const aiChat = { active: false, live: false, listening: false, speaking: false, reviewing: false, busy: false, partial: "", turns: [], recognition: null, stopResolver: null, debrief: "", startedAt: null };

function aiChatNative() {
  const plugin = window.Capacitor?.Plugins?.CloudLibrary;
  return plugin?.startTranscribe ? plugin : null;
}

function aiChatRecognition() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function aiChatVoiceAvailable() {
  return Boolean(aiChatNative() || aiChatRecognition());
}

let nativeTranscriptListenerAdded = false;

function ensureNativeTranscriptListener() {
  const native = aiChatNative();
  if (!native || nativeTranscriptListenerAdded) return;
  native.addListener("transcript", (event) => {
    const text = String(event?.text || "");
    if (aiChat.listening) {
      aiChat.partial = text;
      renderAiChat();
      renderAiLive();
    }
    if (state.speakingNativeTranscribe) {
      state.speakingTranscript = text;
      setText("[data-speaking-status]", text || "正在听…");
    }
  });
  nativeTranscriptListenerAdded = true;
}

function renderAiChat() {
  const ready = aiServiceReady();
  const voiceReady = aiChatVoiceAvailable();
  const log = document.querySelector("[data-ai-chat-log]");
  const mic = document.querySelector("[data-ai-chat-mic]");
  const end = document.querySelector("[data-ai-chat-end]");
  const form = document.querySelector("[data-ai-chat-form]");
  const status = !ready
    ? "先前往 我的 → 设置与资料 → 学习服务 验证 AI 服务，再开始对话。"
    : aiChat.busy
      ? "AI 正在回复…"
      : aiChat.listening
        ? (aiChat.partial ? `正在听：${aiChat.partial}` : "正在听，请说英语；说完点下方按钮发送。")
        : aiChat.active
          ? "对话进行中。"
          : voiceReady
            ? "点下方按钮开始说英语，AI 会语音追问，并在结束后生成个人复盘。"
            : "当前浏览器不支持语音识别，可先使用文字对话。";
  setText("[data-ai-chat-status]", status);
  if (mic) {
    mic.disabled = aiChat.busy;
    mic.setAttribute("aria-pressed", String(aiChat.listening));
    mic.textContent = !ready ? "去设置 AI" : !aiChat.active ? (aiChat.debrief ? "按建议再练一轮" : "开始语音对话") : aiChat.listening ? "说完点这里发送" : "准备中…";
    mic.hidden = !voiceReady && aiChat.active;
  }
  if (end) {
    end.hidden = Boolean(aiChat.debrief) || (!aiChat.active && !aiChat.turns.some((turn) => turn.role === "user"));
    end.textContent = aiChat.busy ? "正在生成复盘…" : "结束并复盘";
    end.disabled = aiChat.busy;
  }
  if (form) {
    const input = form.querySelector("[data-ai-chat-text]");
    const send = form.querySelector("button");
    if (input) input.disabled = !ready;
    if (send) send.disabled = !ready || aiChat.busy;
  }
  if (!log) return;
  const bubbles = aiChat.turns.map((turn) => {
    const bubble = document.createElement("article");
    bubble.className = `ai-chat-turn ${turn.role}`;
    bubble.textContent = turn.text;
    return bubble;
  });
  if (aiChat.listening && aiChat.partial) {
    const live = document.createElement("article");
    live.className = "ai-chat-turn user partial";
    live.textContent = aiChat.partial;
    bubbles.push(live);
  }
  if (aiChat.debrief) {
    const review = document.createElement("article");
    review.className = "ai-chat-debrief";
    review.innerHTML = `<span>SESSION REVIEW · 已写入长期记忆</span>${renderAgentMarkdown(aiChat.debrief)}`;
    bubbles.push(review);
  }
  log.hidden = !bubbles.length;
  log.replaceChildren(...bubbles);
  log.scrollTop = log.scrollHeight;
}

function renderAiLive() {
  const stage = document.querySelector("[data-ai-live]");
  if (!stage) return;
  stage.hidden = !aiChat.live;
  document.querySelector(".phone")?.classList.toggle("ai-live-open", aiChat.live);
  if (!aiChat.live) return;
  const stateName = aiChat.reviewing ? "reviewing" : aiChat.busy ? "thinking" : aiChat.speaking ? "speaking" : aiChat.listening ? "listening" : "ready";
  stage.dataset.state = stateName;
  const labels = { reviewing: "正在总结本轮表现", thinking: "正在思考", speaking: "AI 正在回应", listening: "正在听你说", ready: "准备继续" };
  setText("[data-ai-live-state]", labels[stateName]);
  const latest = aiChat.partial || [...aiChat.turns].reverse().find((turn) => turn.text)?.text || "你可以自然地说英语。";
  setText("[data-ai-live-caption]", latest.length > 118 ? `${latest.slice(0, 118)}…` : latest);
  const toggle = document.querySelector("[data-ai-live-toggle]");
  if (toggle) {
    toggle.disabled = aiChat.busy || aiChat.speaking || aiChat.reviewing;
    toggle.textContent = aiChat.reviewing ? "正在生成复盘" : aiChat.busy ? "AI 正在思考" : aiChat.speaking ? "AI 正在说" : aiChat.listening ? "说完了" : "继续说";
  }
  const finish = document.querySelector("[data-ai-live-finish]");
  if (finish) {
    finish.disabled = aiChat.busy || aiChat.speaking || aiChat.reviewing;
    finish.textContent = aiChat.reviewing ? "总结中" : "结束";
  }
}

async function startAiVoiceChat() {
  if (!aiServiceReady()) return showScreen("settings");
  if (aiChat.active) {
    if (aiChat.listening) return finishAiListeningAndSend();
    return beginAiListening();
  }
  if (!aiChatVoiceAvailable()) { setText("[data-ai-chat-status]", "当前浏览器不支持语音识别，可先用下方文字对话。"); return; }
  aiChat.turns = [];
  aiChat.debrief = "";
  aiChat.speaking = false;
  aiChat.reviewing = false;
  aiChat.busy = false;
  aiChat.startedAt = new Date().toISOString();
  aiChat.active = true;
  aiChat.live = true;
  renderAiLive();
  await beginAiListening();
}

async function beginAiListening() {
  const native = aiChatNative();
  if (!aiChat.active) return;
  try {
    aiChat.partial = "";
    if (native) {
      ensureNativeTranscriptListener();
      await native.startTranscribe();
    } else {
      const Recognition = aiChatRecognition();
      if (!Recognition) throw new Error("当前浏览器不支持语音识别。");
      const recognition = new Recognition();
      recognition.lang = "en-US";
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.onresult = (event) => {
        aiChat.partial = [...event.results].map((result) => result[0]?.transcript || "").join(" ").trim();
        renderAiChat();
        renderAiLive();
      };
      recognition.onerror = (event) => setText("[data-ai-chat-status]", event.error === "not-allowed" ? "麦克风权限未开启。" : "没有听清，请再试一次。");
      recognition.onend = () => {
        const manuallyStopped = Boolean(aiChat.stopResolver);
        aiChat.listening = false;
        aiChat.stopResolver?.();
        aiChat.stopResolver = null;
        if (!manuallyStopped && aiChat.active && aiChat.partial.trim()) {
          const text = aiChat.partial.trim();
          aiChat.partial = "";
          aiChat.recognition = null;
          sendAiChatTurn(text);
        }
        renderAiChat();
        renderAiLive();
      };
      aiChat.recognition = recognition;
      recognition.start();
    }
    aiChat.listening = true;
  } catch (error) {
    aiChat.active = false;
    aiChat.live = false;
    aiChat.listening = false;
    setText("[data-ai-chat-status]", error?.message || "无法启动语音识别。");
  }
  renderAiChat();
  renderAiLive();
}

async function finishAiListeningAndSend() {
  const native = aiChatNative();
  aiChat.listening = false;
  let text = aiChat.partial;
  if (native) {
    try {
      const result = await native.stopTranscribe();
      text = String(result?.text || "") || text;
    } catch (error) { /* keep partial text */ }
  } else if (aiChat.recognition) {
    await new Promise((resolve) => {
      aiChat.stopResolver = resolve;
      aiChat.recognition.stop();
      setTimeout(resolve, 1200);
    });
    text = aiChat.partial;
    aiChat.recognition = null;
  }
  aiChat.partial = "";
  if (text.trim()) return sendAiChatTurn(text.trim());
  renderAiChat();
  if (aiChat.active) {
    setText("[data-ai-chat-status]", "没有听清，请再试一次。");
    beginAiListening();
  }
}

async function sendAiChatTurn(text) {
  if (!aiServiceReady() || aiChat.busy) return;
  aiChat.turns.push({ role: "user", text });
  aiChat.busy = true;
  renderAiChat();
  renderAiLive();
  try {
    const conversation = aiChat.turns.slice(-10).map((turn) => ({ role: turn.role === "user" ? "candidate" : "partner", text: turn.text }));
    const reply = await requestAI("speaking_dialogue", { conversation });
    if (!reply) throw new Error("empty dialogue reply");
    aiChat.turns.push({ role: "ai", text: reply });
    aiChat.busy = false;
    aiChat.speaking = aiChat.active;
    renderAiChat();
    renderAiLive();
    if (aiChat.active) {
      try { await speakAiReply(reply); } catch (error) { /* reply text is already visible */ }
      aiChat.speaking = false;
      renderAiLive();
      if (aiChat.active) beginAiListening();
    }
  } catch (error) {
    aiChat.busy = false;
    setText("[data-ai-chat-status]", "AI 服务暂时不可用，请稍后再试。");
    console.warn("AI dialogue request failed", error);
    renderAiChat();
    renderAiLive();
  }
}

async function speakAiReply(text) {
  const native = aiChatNative();
  if (native?.speak) return native.speak({ text, language: "en-US", wait: true });
  if (!("speechSynthesis" in window)) return;
  await new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.92;
    utterance.onend = resolve;
    utterance.onerror = resolve;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  });
}

async function endAiVoiceChat(createDebrief = false) {
  const native = aiChatNative();
  aiChat.active = false;
  aiChat.listening = false;
  aiChat.speaking = false;
  aiChat.partial = "";
  aiChat.recognition?.stop?.();
  aiChat.recognition = null;
  if (native) {
    native.stopTranscribe().catch(() => {});
    native.stopSpeak?.().catch(() => {});
  }
  window.speechSynthesis?.cancel();
  const userTurns = aiChat.turns.filter((turn) => turn.role === "user");
  if (createDebrief && userTurns.length && aiServiceReady()) {
    aiChat.busy = true;
    aiChat.reviewing = true;
    renderAiChat();
    renderAiLive();
    try {
      const durationSeconds = Math.max(1, Math.round((Date.now() - new Date(aiChat.startedAt || Date.now()).getTime()) / 1000));
      const summary = await requestAI("speaking_debrief", { conversation: aiChat.turns, sessionMeta: { durationSeconds, answerTurns: userTurns.length } });
      if (!summary) throw new Error("empty debrief");
      aiChat.debrief = summary;
      const session = {
        id: `live-${Date.now()}`,
        startedAt: aiChat.startedAt || new Date().toISOString(),
        createdAt: new Date().toISOString(),
        turns: aiChat.turns.slice(-12),
        turnCount: userTurns.length,
      };
      state.aiMemory.dialogueSessions.unshift(session);
      state.aiMemory.dialogueSessions = state.aiMemory.dialogueSessions.slice(0, 20);
      state.aiMemory.speakingDebriefs.unshift({ sessionId: session.id, summary, createdAt: session.createdAt });
      state.aiMemory.speakingDebriefs = state.aiMemory.speakingDebriefs.slice(0, 20);
      persistAiMemory();
      rememberModuleReview("Speaking", summary, { sourceId: session.id, answerTurns: userTurns.length, durationSeconds });
      trackLearningEvent({ module: "Speaking", activity: "AI 实时对练与复盘", durationMinutes: Math.max(1, Math.round((Date.now() - new Date(session.startedAt).getTime()) / 60000)), sourceId: session.id, evidenceType: "ai-coaching" });
    } catch (error) {
      setText("[data-ai-chat-status]", "会话已保留，但 AI 复盘暂时生成失败，可稍后再试。");
    }
  }
  aiChat.busy = false;
  aiChat.reviewing = false;
  aiChat.live = false;
  renderAiMemory();
  renderAiChat();
  renderAiLive();
}

const agentChat = { busy: false, turns: [], greeted: false };

function aiProviderLabel() {
  return localStorage.getItem(AI_PROVIDER_KEY) || "AI 服务";
}

// Minimal safe markdown for agent replies: escape first, then restore the few
// constructs the study agent actually emits (headings, bold, lists, breaks).
function renderAgentMarkdown(text) {
  const escaped = String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const lines = escaped.split("\n").map((line) => {
    let html = line.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    if (/^#{1,4}\s/.test(html)) return `<h4>${html.replace(/^#{1,4}\s*/, "")}</h4>`;
    if (/^\s*[-*]\s+/.test(html)) return `<li>${html.replace(/^\s*[-*]\s+/, "")}</li>`;
    return html;
  });
  const out = [];
  let inList = false;
  for (const html of lines) {
    if (html.startsWith("<li>")) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(html);
    } else {
      if (inList) { out.push("</ul>"); inList = false; }
      if (html.trim()) out.push(`<p>${html}</p>`);
    }
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

function renderAgentChat() {
  const ready = aiServiceReady();
  const log = document.querySelector("[data-agent-log]");
  const form = document.querySelector("[data-agent-form]");
  const chips = document.querySelector("[data-agent-chips]");
  setText("[data-agent-status]", !ready
    ? aiAutoConfiguring
      ? "正在连接 AI 服务…"
      : "AI 服务未连接，私教暂时无法查阅你的学习数据。"
    : agentChat.busy
      ? "私教正在查阅你的学习数据，免费档模型需要 15-60 秒…"
      : `已连接 ${aiProviderLabel()}；回答基于你的本地学习数据。`);
  if (form) {
    const input = form.querySelector("[data-agent-text]");
    const send = form.querySelector("button");
    if (input) input.disabled = !ready || agentChat.busy;
    if (send) send.disabled = !ready || agentChat.busy;
  }
  if (chips) chips.hidden = agentChat.turns.length > 0;
  if (!log) return;
  const nodes = [];
  for (const turn of agentChat.turns) {
    if (turn.trace?.length) {
      const wrap = document.createElement("div");
      wrap.className = "agent-trace";
      for (const step of turn.trace) {
        const chip = document.createElement("div");
        chip.className = "agent-tool";
        const label = document.createElement("span");
        label.innerHTML = "<b></b> <span class=\"args\"></span>";
        label.querySelector("b").textContent = step.tool;
        label.querySelector(".args").textContent = JSON.stringify(step.args);
        const result = document.createElement("span");
        result.className = "result";
        result.textContent = JSON.stringify(step.result).slice(0, 120);
        chip.append(label, result);
        wrap.appendChild(chip);
      }
      nodes.push(wrap);
    }
    const bubble = document.createElement("article");
    bubble.className = `ai-chat-turn ${turn.role === "user" ? "user" : "agent"}`;
    if (turn.role === "user") bubble.textContent = turn.text;
    else bubble.innerHTML = renderAgentMarkdown(turn.text);
    nodes.push(bubble);
  }
  if (agentChat.busy) {
    const pending = document.createElement("article");
    pending.className = "ai-chat-turn partial";
    pending.textContent = "正在思考并调用工具…";
    nodes.push(pending);
  }
  log.hidden = !nodes.length;
  log.replaceChildren(...nodes);
  log.scrollTop = log.scrollHeight;
}

async function requestAgent(message) {
  const endpoint = configuredAIEndpoint();
  const response = await fetch(`${endpoint}/api/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, context: learningMemorySnapshot() }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `agent request failed: ${response.status}`);
  return result;
}

async function sendAgentMessage(text) {
  if (agentChat.busy) return;
  if (!aiServiceReady()) {
    autoConfigureAIEndpoint();
    return showToast(aiAutoConfiguring ? "正在连接 AI 服务，请稍候再试。" : "AI 服务未连接，请先启动本地服务或在设置中验证地址。", "error");
  }
  agentChat.turns.push({ role: "user", text });
  agentChat.busy = true;
  renderAgentChat();
  try {
    // The free cloud tier flakes occasionally; retry once before giving up.
    const result = await requestAgent(text).catch(async (error) => {
      await new Promise((resolve) => setTimeout(resolve, 2500));
      return requestAgent(text).catch(() => { throw error; });
    });
    const reply = String(result.text || "").trim();
    if (!reply) throw new Error("empty agent reply");
    agentChat.turns.push({ role: "ai", text: reply, trace: result.trace || [] });
    rememberAgentExchange(text, reply);
  } catch (error) {
    console.warn("agent request failed", error);
    agentChat.turns.push({ role: "ai", text: `私教刚才没连上模型（${error.message}）。云端免费档偶尔会繁忙，稍等几秒再发一次通常就好了。` });
  } finally {
    agentChat.busy = false;
    renderAgentChat();
  }
}

// When the app is served by the local agent server itself, adopt that origin
// as the AI endpoint so the demo works without any manual settings.
let aiAutoConfiguring = false;

async function autoConfigureAIEndpoint() {
  if (configuredAIEndpoint() || aiAutoConfiguring || !/^https?:$/.test(location.protocol)) return;
  const origin = location.origin.replace(/\/$/, "");
  aiAutoConfiguring = true;
  renderAIAssistant();
  try {
    // Cloud health does a live chat probe, which can take 20s+ on a cold model.
    const response = await fetch(`${origin}/api/health`, { signal: AbortSignal.timeout?.(45_000) });
    const health = await response.json().catch(() => ({}));
    if (!response.ok || health.ok !== true) throw new Error("health failed");
    persistValue(AI_ENDPOINT_KEY, origin);
    persistValue(AI_VERIFIED_ENDPOINT_KEY, origin);
    persistValue(AI_PROVIDER_KEY, `${health.provider || "AI 服务"}${health.model ? ` · ${health.model}` : ""}`);
  } catch { /* static hosting without the agent API: stay on local rules */ }
  aiAutoConfiguring = false;
  renderAIAssistant();
}

function renderLearningTimeline() {
  const range = state.timelineDays === 30 ? 30 : 7;
  const dates = Array.from({ length: range }, (_, index) => localIsoDate(-index));
  const groups = dates.map((date) => {
    const events = state.learningEvents.filter((event) => localDateOf(event.createdAt) === date).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    return { date, events, minutes: events.reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0) };
  }).filter((group) => group.events.length);
  const total = groups.reduce((sum, group) => sum + group.minutes, 0);
  const scored = groups.flatMap((group) => group.events).filter((event) => eventBand(event) !== null);
  setText("[data-timeline-total]", `${total} 分钟`);
  setText("[data-timeline-summary]", groups.length ? `${groups.length} 个学习日 · ${scored.length} 个有效估分样本 · 每个学习日平均 ${Math.round(total / groups.length)} 分钟` : "这段时间还没有记录；完成一次单词、练习、写作或口语即可开始累计。" );
  document.querySelectorAll("[data-timeline-days]").forEach((button) => {
    button.classList.toggle("selected", Number(button.dataset.timelineDays) === range);
    button.onclick = () => { state.timelineDays = Number(button.dataset.timelineDays); renderLearningTimeline(); };
  });
  const list = document.querySelector("[data-learning-timeline]");
  if (!list) return;
  list.innerHTML = groups.length ? groups.map((group) => {
    const day = new Date(`${group.date}T12:00:00`);
    const label = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "short" }).format(day);
    return `<article><header><strong>${label}</strong><span>${group.minutes} 分钟</span></header><div>${group.events.map((event) => {
      const band = eventBand(event);
      const time = new Date(event.createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
      return `<div class="timeline-event"><i>${escapeHtml(MODULE_LABELS[event.module] || event.module).slice(0, 1)}</i><p><strong>${escapeHtml(event.activity || "学习记录")}</strong><span>${time} · ${Math.round(Number(event.durationMinutes || 0))} 分钟</span></p>${band !== null ? `<em>估 ${band.toFixed(1)}</em>` : ""}</div>`;
    }).join("")}</div></article>`;
  }).join("") : "<article class=\"empty-state\"><strong>暂无学习记录</strong><p>开始一项练习后，学习时间、完成动作和估分都会在这里留下记录。</p><button data-go=\"practice\">开始练习</button></article>";
  list.querySelector("[data-go]")?.addEventListener("click", () => showScreen("practice"));
}

function renderContentStatus() {
  const allTestItems = (state.tests?.collections || []).flatMap((collection) => collection.items.map((item) => ({ ...item, collectionId: collection.id })));
  const links = [Object.keys(state.listeningManualMap).length, Object.keys(state.readingSourceMap).length, Object.keys(state.writingSourceMap).length, Object.keys(state.speakingSourceMap).length];
  const verifiedBooks = (module) => [...new Set((state.contentManifest?.records || []).filter((item) => item.module === module && item.status === "ready").map((item) => item.book))].sort((a, b) => a - b);
  const verifiedLabel = (module) => verifiedBooks(module).map((book) => `C${book}`).join(" / ") + " 已核验";
  const statuses = [
    ["单词", `${state.wordbook?.words?.length || 0} 词`, "完整版词库"],
    ["听力", `${allTestItems.filter((item) => item.type === "Listening" && !item.cloudOnly).length} 节`, verifiedLabel("Listening")],
    ["阅读", `${allTestItems.filter((item) => item.type === "Reading" && !item.cloudOnly).length} 篇`, verifiedLabel("Reading")],
    ["写作", `${state.writing?.tasks?.length || 0} 题`, verifiedLabel("Writing")],
    ["口语", `${SPEAKING_CARDS.length} 题卡`, "原创 Part 1/2/3"],
    ["云端资料", `${allTestItems.filter((item) => item.cloudOnly).length} 项`, "已索引待转换"],
    ["已关联", `${links.reduce((sum, value) => sum + value, 0)} 条`, `听${links[0]} · 读${links[1]} · 写${links[2]} · 说${links[3]}`],
  ];
  const container = document.querySelector("[data-content-status]");
  if (container) container.innerHTML = statuses.map(([label, value, meta]) => `<article><span>${label}</span><strong>${value}</strong><small>${meta}</small></article>`).join("");
  const packStatus = document.querySelector("[data-practice-pack-status]");
  if (packStatus) packStatus.innerHTML = ["Listening", "Reading", "Writing", "Speaking"].map((module) => {
    const count = module === "Speaking" ? SPEAKING_CARDS.length : allTestItems.filter((item) => item.type === module && !item.cloudOnly).length;
    return `<article class="ready"><strong>${MODULE_LABELS[module]}</strong><span>${count} 个原创入口</span><small>可关联个人资料，不随仓库分发</small></article>`;
  }).join("");
}

function renderDataHealth() {
  const logs = loadStoredArray(ERROR_LOG_KEY);
  const recovery = loadStoredJson(RECOVERY_KEY, [], (value) => Array.isArray(value) || (value && typeof value === "object"));
  const recoveryCount = Array.isArray(recovery) ? recovery.length : 1;
  const eventKeys = new Set();
  let duplicates = 0;
  state.learningEvents.forEach((event) => {
    const key = `${event.module}|${event.activity}|${event.sourceId}|${Math.floor(new Date(event.createdAt).getTime() / 10000)}`;
    if (eventKeys.has(key)) duplicates += 1;
    eventKeys.add(key);
  });
  const drafts = Object.values(state.writingDrafts).filter((draft) => draft.text || draft.notes).length;
  setText("[data-health-status]", `${state.learningEvents.length} 条学习记录 · ${drafts} 份草稿 · ${logs.length} 条错误${duplicates ? ` · ${duplicates} 条历史重复` : ""}${recoveryCount ? ` · 已保留 ${recoveryCount} 份恢复副本` : ""}`);
  const list = document.querySelector("[data-error-log]");
  if (list) list.innerHTML = logs.length ? logs.slice(0, 3).map((item) => `<p><strong>${escapeHtml(item.source || "app")}</strong><span>${escapeHtml(item.message)}</span><em>${new Date(item.createdAt).toLocaleString("zh-CN")}</em></p>`).join("") : "<p>最近没有运行错误。</p>";
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function localStorageBytes() {
  return new TextEncoder().encode(Object.entries(localStorage).map(([key, value]) => `${key}${value}`).join("")).byteLength;
}

async function cacheStorageBytes() {
  if (!("caches" in window)) return 0;
  let bytes = 0;
  for (const name of await caches.keys()) {
    const cache = await caches.open(name);
    for (const request of await cache.keys()) {
      const response = await cache.match(request);
      if (response) bytes += (await response.clone().blob()).size;
    }
  }
  return bytes;
}

function mediaDownloads() {
  return loadStoredArray(MEDIA_DOWNLOADS_KEY);
}

async function toggleMediaDownload(url, label, button) {
  if (!("caches" in window) || !url) return showToast("当前环境不支持离线下载。", "error");
  setButtonBusy(button, true, "处理中…");
  try {
    const cache = await caches.open(MEDIA_CACHE_NAME);
    const existing = await cache.match(url);
    if (existing) {
      await cache.delete(url);
      if (!persistValue(MEDIA_DOWNLOADS_KEY, JSON.stringify(mediaDownloads().filter((item) => item.url !== url)))) throw new Error("metadata save failed");
      showToast("离线音频已删除，之后继续在线播放。", "success");
    } else {
      const response = await fetch(url);
      if (!response.ok && response.type !== "opaque") throw new Error("download failed");
      const bytes = response.type === "opaque" ? 0 : (await response.clone().blob()).size;
      const downloadedBytes = mediaDownloads().reduce((total, item) => total + Number(item.bytes || 0), 0);
      if (bytes > OFFLINE_MEDIA_LIMIT_BYTES || downloadedBytes + bytes > OFFLINE_MEDIA_LIMIT_BYTES) {
        showToast("离线音频上限为 250 MB。请先清理已下载内容，视频始终在线播放。", "error");
        return;
      }
      await cache.put(url, response);
      if (!persistValue(MEDIA_DOWNLOADS_KEY, JSON.stringify([{ url, label, bytes, savedAt: new Date().toISOString(), lastUsed: new Date().toISOString() }, ...mediaDownloads().filter((item) => item.url !== url)]))) throw new Error("metadata save failed");
      showToast("已下载，可离线播放。", "success");
    }
  } catch (error) {
    showToast("下载失败，请检查网络或内容地址。", "error");
  } finally {
    setButtonBusy(button, false);
  }
  renderNativeAudioPlayer(activeListeningItem());
  renderStorageStatus();
}

async function pruneMediaDownloads(maxAgeDays = OFFLINE_MEDIA_MAX_AGE_DAYS) {
  if (!("caches" in window)) return;
  const cutoff = Date.now() - maxAgeDays * 86400000;
  const downloads = mediaDownloads();
  const stale = downloads.filter((item) => new Date(item.lastUsed || item.savedAt).getTime() < cutoff);
  if (!stale.length) return;
  const cache = await caches.open(MEDIA_CACHE_NAME);
  await Promise.all(stale.map((item) => cache.delete(item.url)));
  persistValue(MEDIA_DOWNLOADS_KEY, JSON.stringify(downloads.filter((item) => !stale.includes(item))));
}

async function clearMediaDownloads() {
  if ("caches" in window) await caches.delete(MEDIA_CACHE_NAME);
  removePersistedValue(MEDIA_DOWNLOADS_KEY);
  await renderStorageStatus();
  showToast("离线音视频已清理；学习记录不受影响。");
}

async function renderStorageStatus() {
  try {
    const [cacheBytes, estimate] = await Promise.all([
      cacheStorageBytes(),
      navigator.storage?.estimate?.() || Promise.resolve({ usage: 0 }),
    ]);
    setText("[data-storage-learning]", formatBytes(localStorageBytes()));
    setText("[data-storage-cache]", formatBytes(cacheBytes));
    setText("[data-storage-total]", formatBytes(Number(estimate.usage || 0)));
    const downloads = mediaDownloads();
    const list = document.querySelector("[data-offline-media-list]");
    if (list) list.innerHTML = downloads.length ? downloads.map((item) => `<p><span>${escapeHtml(item.label || "离线媒体")}</span><strong>${formatBytes(item.bytes)}</strong></p>`).join("") : "<p><span>离线内容</span><strong>暂无</strong></p>";
    const mediaBytes = downloads.reduce((total, item) => total + Number(item.bytes || 0), 0);
    setText("[data-storage-status]", `${downloads.length} 个离线音频，共 ${formatBytes(mediaBytes)} / 250 MB；超过 ${OFFLINE_MEDIA_MAX_AGE_DAYS} 天未使用会自动清理。视频始终在线播放。`);
  } catch (error) {
    setText("[data-storage-status]", "当前环境无法读取精确占用，学习数据仍会正常保存。");
  }
}

async function clearTemporaryStorage() {
  if ("caches" in window) await Promise.all((await caches.keys()).filter((name) => name !== MEDIA_CACHE_NAME && !name.startsWith("ielts-os-demo-")).map((name) => caches.delete(name)));
  removePersistedValue(DAILY_NEWS_CACHE_KEY);
  removePersistedValue(DAILY_WORD_QUEUE_KEY);
  await renderStorageStatus();
  showToast("临时缓存已清理；学习进度、错题和草稿均已保留。");
}

function repairLearningEvents() {
  const latest = new Map();
  const before = state.learningEvents.length;
  state.learningEvents = state.learningEvents.filter((event) => {
    const key = `${event.module}|${event.activity}|${event.sourceId}`;
    const time = new Date(event.createdAt).getTime();
    const previous = latest.get(key);
    latest.set(key, time);
    return previous === undefined || Math.abs(previous - time) >= 10000;
  });
  persistLearningEvents();
  refreshLearningSurfaces();
  showToast(before === state.learningEvents.length ? "数据检查完成，没有发现重复学习记录。" : `已清理 ${before - state.learningEvents.length} 条重复学习记录。`);
}

function renderLearningDashboard() {
  const snapshot = dashboardSnapshot();
  document.querySelectorAll("[data-dashboard-range]").forEach((button) => button.classList.toggle("selected", Number(button.dataset.dashboardRange) === snapshot.rangeDays));
  setText("[data-dashboard-period]", `近 ${snapshot.rangeDays} 天 · ${snapshot.totalMinutes} 分钟`);
  setText("[data-dashboard-freshness]", snapshot.latest ? `更新：${new Date(snapshot.latest.createdAt).toLocaleDateString("zh-CN")}` : "来源：本机学习记录");

  const kpis = document.querySelector("[data-dashboard-kpis]");
  if (kpis) {
    const completion = snapshot.planTotal ? Math.round(snapshot.completed / snapshot.planTotal * 100) : 0;
    kpis.innerHTML = `
      <div><span>今日完成</span><strong>${completion}%</strong><small>${snapshot.completed}/${snapshot.planTotal} 项</small></div>
      <div><span>学习投入</span><strong>${snapshot.totalMinutes}</strong><small>分钟</small></div>
      <div><span>活跃天数</span><strong>${snapshot.activeDays}</strong><small>共 ${snapshot.rangeDays} 天</small></div>
      <div><span>待复盘</span><strong>${snapshot.dueReviews}</strong><small>到期错题</small></div>`;
  }

  const trend = document.querySelector("[data-dashboard-trend]");
  if (trend) {
    const maximum = Math.max(30, ...snapshot.daily.map((day) => day.minutes));
    trend.innerHTML = snapshot.daily.map((day, index) => {
      const date = new Date(`${day.date}T12:00:00`);
      const label = snapshot.rangeDays === 7 || index % 5 === 0 || index === snapshot.daily.length - 1
        ? new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date)
        : "";
      return `<div title="${day.date} · ${day.minutes} 分钟"><strong>${day.minutes || ""}</strong><i><b style="height:${Math.max(day.minutes ? 5 : 2, day.minutes / maximum * 100)}%"></b></i><span>${label}</span></div>`;
    }).join("");
  }

  const mix = document.querySelector("[data-dashboard-mix]");
  if (mix) {
    const rows = Object.entries(snapshot.moduleMinutes).sort((a, b) => b[1] - a[1]);
    const maximum = Math.max(1, ...rows.map(([, value]) => value));
    mix.innerHTML = rows.map(([module, value]) => `<div><span>${MODULE_LABELS[module]}</span><i><b style="width:${value / maximum * 100}%"></b></i><strong>${Math.round(value)}</strong></div>`).join("");
  }

  const movement = document.querySelector("[data-dashboard-movement]");
  if (movement) movement.innerHTML = snapshot.movement.map((item) => {
    const delta = item.delta === null ? "待积累" : `${item.delta > 0 ? "↑" : item.delta < 0 ? "↓" : "→"}${Math.abs(item.delta).toFixed(1)}`;
    const tone = item.delta === null ? "" : item.delta > 0 ? "positive" : item.delta < 0 ? "negative" : "neutral";
    return `<div><span>${MODULE_LABELS[item.module]}</span><strong>${item.current === null ? "—" : item.current.toFixed(1)}</strong><em class="${tone}">${delta}</em><small>${item.samples} 个近期样本</small></div>`;
  }).join("");

  const report = document.querySelector("[data-weekly-report]");
  if (report) {
    const weekly = dashboardSnapshot(7);
    const invested = Object.entries(weekly.moduleMinutes).sort((a, b) => b[1] - a[1])[0];
    const weakest = assessmentSnapshot().details.filter((item) => item.score !== null).sort((a, b) => a.score - b.score)[0];
    const priorities = learningPriorities();
    const priority = priorities[0];
    const previousDates = new Set(Array.from({ length: 7 }, (_, index) => localIsoDate(index - 13)));
    const previousMinutes = state.learningEvents.filter((event) => previousDates.has(localDateOf(event.createdAt))).reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0);
    const timeDelta = weekly.totalMinutes - previousMinutes;
    const strongestMove = weekly.movement.filter((item) => item.delta !== null).sort((a, b) => b.delta - a.delta)[0];
    const activeWrong = state.userWrongQuestions;
    const masteredThisWeek = activeWrong.filter((item) => item.status === "已掌握" && item.reviewedAt && localDateOf(item.reviewedAt) >= localIsoDate(-6)).length;
    const mocks = state.learningEvents.filter((event) => event.module === "Review" && event.activity === "完整阶段测评" && localDateOf(event.createdAt) >= localIsoDate(-6)).length;
    const resourcesDone = Object.values(state.resourceProgress).filter((item) => item.completedAt && localDateOf(item.completedAt) >= localIsoDate(-6)).length;
    report.innerHTML = `<span>WEEKLY REVIEW</span><h3>${weekly.totalMinutes ? `本周重点投入：${MODULE_LABELS[invested[0]]}` : "本周从第一项任务开始"}</h3><div class="weekly-report-metrics"><span><strong>${weekly.totalMinutes}</strong> 分钟</span><span><strong>${weekly.activeDays}</strong> 天学习</span><span><strong>${masteredThisWeek}</strong> 题掌握</span><span><strong>${mocks}</strong> 次测评</span></div><ul><li>投入：比上个 7 天${timeDelta >= 0 ? "多" : "少"} ${Math.abs(timeDelta)} 分钟</li><li>能力：${strongestMove ? `${MODULE_LABELS[strongestMove.module]} ${strongestMove.delta >= 0 ? "提升" : "回落"} ${Math.abs(strongestMove.delta).toFixed(1)}` : "带分数练习不足，继续积累有效样本"}</li><li>资料：本周完成 ${resourcesDone} 份 iCloud 资料</li><li>${weakest ? `当前薄弱：${MODULE_LABELS[weakest.module]} ${weakest.score.toFixed(1)}` : "当前校准：有效样本不足"}</li></ul><div class="weekly-objectives"><strong>下周 3 个目标</strong>${priorities.slice(0, 3).map((item, index) => `<p><span>0${index + 1}</span>${escapeHtml(MODULE_LABELS[item.module])} · ${escapeHtml(item.reason)}</p>`).join("")}</div><button>按这份计划继续</button>`;
    report.querySelector("button")?.addEventListener("click", () => showScreen("plan"));
  }
}

function renderAssessment() {
  const snapshot = assessmentSnapshot();
  const sessionProgress = assessmentProgress();
  const completed = sessionProgress.filter((item) => item.event).length;
  setText("[data-assessment-band]", snapshot.band === null ? "—" : snapshot.band.toFixed(1));
  setText("[data-assessment-confidence]", `${snapshot.confidence} · ${snapshot.samples} 个有效样本`);
  const container = document.querySelector("[data-assessment-modules]");
  if (container) container.replaceChildren(...snapshot.details.map((item) => {
    const checkpoint = sessionProgress.find((entry) => entry.module === item.module);
    const assignment = checkpoint?.assignment;
    const card = document.createElement("article");
    card.innerHTML = `
      <div><span>${escapeHtml(MODULE_LABELS[item.module])}</span><strong>${checkpoint?.event ? "✓" : item.score === null ? "—" : item.score.toFixed(1)}</strong></div>
      <p>${checkpoint?.event ? `本次已完成 · ${checkpoint.completed}/${checkpoint.total} 项` : assignment ? `${assignment.title} · ${checkpoint.completed}/${checkpoint.total} 项 · 约 ${assignment.minutes} 分钟` : `${item.samples}/${item.required} 个有效样本${item.ready ? " · 已达门槛" : ""}`}</p>
      <button>${checkpoint?.event ? "重新作答" : assignment ? "开始本项" : "开始测评"}</button>
    `;
    card.querySelector("button").addEventListener("click", () => assignment ? openAssessmentAssignment(assignment) : startAssessment());
    return card;
  }));

  const weakest = snapshot.details.filter((item) => item.score !== null).sort((a, b) => a.score - b.score)[0];
  const result = snapshot.band === null
    ? `目前只有 ${snapshot.completedModules}/4 科有有效样本。先完成听力与阅读客观题；写作与口语本地反馈不计入正式估分。`
    : snapshot.completedModules < 2
      ? "当前显示首次自评结果。完成听力与阅读客观题后会逐步替换；写作与口语仍需可靠评阅。"
      : `阶段估分 ${snapshot.band.toFixed(1)}（${snapshot.confidence}）；薄弱项为${MODULE_LABELS[weakest.module]} ${weakest.score.toFixed(1)}，下一阶段优先校准该科。`;
  setText("[data-assessment-result]", result);
  setText("[data-assessment-progress]", `${completed} / 4`);
  const title = state.assessmentSession?.mode === "full-mock" ? `C${state.assessmentSession.book} Test ${state.assessmentSession.test} 完整模考` : "四科阶段测评";
  setText("[data-assessment-session-title]", state.assessmentSession?.completedAt ? `测评已完成 · ${Number.isFinite(Number(state.assessmentSession.band)) ? Number(state.assessmentSession.band).toFixed(1) : "部分能力待校准"}` : state.assessmentSession ? title : "开始一次完整阶段测评");
  const next = state.assessmentSession?.assignments?.find((item) => !state.assessmentSession.completed?.[item.practiceId]);
  const totalSteps = state.assessmentSession?.assignments?.length || 0;
  const completedSteps = state.assessmentSession?.assignments?.filter((item) => state.assessmentSession.completed?.[item.practiceId]).length || 0;
  setText("[data-assessment-session-status]", state.assessmentSession?.completedAt ? "结果已保存，可随时开始下一轮校准。" : state.assessmentSession ? `已完成 ${completedSteps}/${totalSteps} 个步骤；下一项：${next ? `${next.title}（约 ${next.minutes} 分钟）` : "生成 7 天计划"}。` : "进度会保存在本机，可分多次完成。");
  const startButton = document.querySelector("[data-assessment-start]");
  if (startButton) startButton.textContent = state.assessmentSession?.completedAt ? "开始新一轮" : state.assessmentSession ? "继续测评" : "开始测评";
  const reviewButton = document.querySelector("[data-assessment-review]");
  if (reviewButton) reviewButton.textContent = state.assessmentSession && !state.assessmentSession.completedAt ? "完成并生成计划" : "更新阶段结论";
  const planCard = document.querySelector("[data-assessment-plan]");
  const plan = state.assessmentSession?.plan || [];
  if (planCard) planCard.hidden = !plan.length;
  const planList = document.querySelector("[data-assessment-plan-list]");
  if (planList) planList.innerHTML = plan.map((item) => `<div><span>DAY ${String(item.day).padStart(2, "0")}</span><strong>${escapeHtml(MODULE_LABELS[item.module] || "复盘")}</strong><p>${escapeHtml(item.task)} · ${item.minutes} 分钟</p></div>`).join("");

  const report = assessmentReport();
  const reportCard = document.querySelector("[data-assessment-report]");
  if (reportCard) reportCard.hidden = !report;
  if (!report) {
    const wrongCard = document.querySelector("[data-assessment-wrong-review]");
    if (wrongCard) wrongCard.hidden = true;
    return;
  }
  setText("[data-assessment-report-band]", report.band === null ? "—" : report.band.toFixed(1));
  setText("[data-assessment-report-title]", state.assessmentSession?.mode === "full-mock" ? `C${state.assessmentSession.book} Test ${state.assessmentSession.test} · 模考报告` : "阶段测评报告");
  const timeText = report.totalMinutes ? `本次记录 ${report.totalMinutes} 分钟（建议 ${report.targetMinutes} 分钟）` : `建议总时长 ${report.targetMinutes} 分钟`;
  setText("[data-assessment-report-summary]", `${timeText}；下一周期优先补齐 ${MODULE_LABELS[report.weakest.module]}。`);
  const grid = document.querySelector("[data-assessment-report-grid]");
  if (grid) grid.innerHTML = report.modules.map((item) => `<div><span>${MODULE_LABELS[item.module]}</span><strong>${item.score === null ? "—" : item.score.toFixed(1)}</strong><small>${item.score === null ? "完成训练 · 未校准" : item.wrong ? `${item.wrong} 道错题` : "已完成"}</small></div>`).join("");
  const focus = document.querySelector("[data-assessment-report-focus]");
  if (focus) focus.innerHTML = `<strong>本周第一优先：${MODULE_LABELS[report.weakest.module]}</strong><p>${report.weakest.wrong ? `先处理本次 ${report.weakest.wrong} 道错题，再做一组同题型练习。` : report.weakest.score === null ? "本次已完成训练，但没有可靠评分；先继续积累可校准样本。" : `本次估分 ${report.weakest.score.toFixed(1)}，连续安排 3 次针对性训练。`}</p>`;
  const action = document.querySelector("[data-assessment-report-action]");
  action?.addEventListener("click", () => showScreen(MODULE_TARGETS[report.weakest.module]));

  const wrongItems = assessmentWrongItems();
  const wrongCard = document.querySelector("[data-assessment-wrong-review]");
  if (wrongCard) wrongCard.hidden = !wrongItems.length;
  if (!wrongItems.length) return;
  const unresolved = wrongItems.filter((item) => !isWrongMastered(item));
  const due = wrongReviewQueue(wrongItems).length;
  const grouped = Object.entries(unresolved.reduce((result, item) => {
    const key = `${MODULE_LABELS[item.module] || item.module} · ${item.category || wrongTypeLabel(item.mistakeType)}`;
    result[key] = (result[key] || 0) + 1;
    return result;
  }, {})).sort((a, b) => b[1] - a[1]);
  setText("[data-assessment-wrong-count]", unresolved.length);
  setText("[data-assessment-wrong-summary]", due ? `其中 ${due} 道今天应复盘；先从出现最多的题型开始。` : "已自动安排间隔复习；可先回看最常出错的题型。");
  const types = document.querySelector("[data-assessment-wrong-types]");
  if (types) types.innerHTML = grouped.slice(0, 3).map(([label, count]) => `<div><span>${escapeHtml(label)}</span><strong>${count} 道</strong></div>`).join("");
  const wrongAction = document.querySelector("[data-assessment-wrong-action]");
  if (wrongAction) {
    wrongAction.textContent = `复盘本次 ${unresolved.length} 道错题`;
    wrongAction.addEventListener("click", openAssessmentWrongReview);
  }
}

function speakingDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(SPEAKING_DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("recordings", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function loadSpeakingRecordings() {
  const database = await speakingDatabase();
  const records = await new Promise((resolve, reject) => {
    const request = database.transaction("recordings").objectStore("recordings").getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  database.close();
  return records.sort((a, b) => b.id - a.id);
}

async function ensureSpeakingRecordings() {
  if (state.speakingRecordingsLoaded) return renderSpeakingRecordings();
  state.speakingRecordingsLoaded = true;
  try {
    state.speakingRecordings = await loadSpeakingRecordings();
  } catch (error) {
    console.warn("Failed to read speaking recordings", error);
  }
  renderSpeakingRecordings();
}

async function saveSpeakingRecording(recording) {
  const database = await speakingDatabase();
  await new Promise((resolve, reject) => {
    const request = database.transaction("recordings", "readwrite").objectStore("recordings").put(recording);
    request.onsuccess = resolve;
    request.onerror = () => reject(request.error);
  });
  database.close();
}

function speakingDuration(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const SPEAKING_CARDS = [
  { id: "speaking-hometown-part1", part: "Part 1", meta: "INTERVIEW · 20–30 SEC", title: "Home town", question: "What do you like most about your home town?", points: ["Give a direct answer", "Add one reason", "Give a small example"], prep: 0 },
  { id: "speaking-routine-part1", part: "Part 1", meta: "INTERVIEW · 20–30 SEC", title: "Daily routine", question: "Which part of your daily routine would you like to change?", points: ["Name the routine", "Explain the problem", "Describe one change"], prep: 0 },
  { id: "speaking-local-food-part1", part: "Part 1", meta: "INTERVIEW · 20–30 SEC", title: "Local food", question: "What local food would you recommend to a visitor?", points: ["Name the food", "Describe its taste", "Say when people eat it"], prep: 0 },
  { id: "speaking-quiet-place-part1", part: "Part 1", meta: "INTERVIEW · 20–30 SEC", title: "Quiet places", question: "Where do you go when you need a quiet place to think?", points: ["Name the place", "Describe the setting", "Explain why it helps"], prep: 0 },
  { id: "speaking-journey-part2", part: "Part 2", meta: "LONG TURN · 1–2 MIN", title: "A memorable journey", question: "Describe a journey that you remember well.", points: ["Where and when you went", "Who travelled with you", "What happened", "Why you remember it"], prep: 60 },
  { id: "speaking-skill-part2", part: "Part 2", meta: "LONG TURN · 1–2 MIN", title: "A useful skill", question: "Describe a useful skill that you learned outside school.", points: ["What the skill is", "How you learned it", "When you use it", "Why it matters to you"], prep: 60 },
  { id: "speaking-helper-part2", part: "Part 2", meta: "LONG TURN · 1–2 MIN", title: "A helpful person", question: "Describe a person who helped you solve a difficult problem.", points: ["Who the person was", "What the problem was", "How the person helped", "What you learned"], prep: 60 },
  { id: "speaking-technology-part2", part: "Part 2", meta: "LONG TURN · 1–2 MIN", title: "Useful technology", question: "Describe a piece of technology that saves you time.", points: ["What it is", "How you use it", "What it replaced", "Why it is useful"], prep: 60 },
  { id: "speaking-transport-part3", part: "Part 3", meta: "DISCUSSION · 40–60 SEC", title: "Public transport", question: "How can cities encourage people to use public transport?", points: ["State a clear view", "Explain cause and effect", "Compare possible solutions"], prep: 0 },
  { id: "speaking-green-space-part3", part: "Part 3", meta: "DISCUSSION · 40–60 SEC", title: "Urban green space", question: "Should growing cities protect more land for public parks?", points: ["Give a position", "Consider competing needs", "Offer a practical policy"], prep: 0 },
  { id: "speaking-remote-work-part3", part: "Part 3", meta: "DISCUSSION · 40–60 SEC", title: "Remote work", question: "How might remote work change city life in the next decade?", points: ["Describe one change", "Explain who benefits", "Mention one possible drawback"], prep: 0 },
  { id: "speaking-learning-tech-part3", part: "Part 3", meta: "DISCUSSION · 40–60 SEC", title: "Learning technology", question: "What should teachers consider before using AI tools in class?", points: ["Set one principle", "Give a classroom example", "Address one risk"], prep: 0 },
];
const SPEAKING_FOLLOW_UPS = [
  "Why is that important to you?",
  "Can you give me a specific example?",
  "Has your opinion changed since you were younger?",
  "What could make your home town better in the future?",
];

function selectSpeakingCard(index) {
  if (!SPEAKING_CARDS[index]) return;
  state.speakingCardIndex = index;
  const current = state.speakingSessions.find((item) => item.id === state.activeSpeakingSessionId);
  if (current?.cardIndex !== index) {
    state.activeSpeakingSessionId = null;
    activeSpeakingSession();
  }
  if (state.speakingPrepTimerId) clearInterval(state.speakingPrepTimerId);
  state.speakingPrepTimerId = null;
  state.speakingPrepSeconds = SPEAKING_CARDS[index].prep;
  renderSpeakingCoach();
}

function toggleSpeakingPrep() {
  const card = SPEAKING_CARDS[state.speakingCardIndex];
  if (!card.prep) return showToast("此题型无需单独准备，直接开始回答即可。");
  if (state.speakingPrepTimerId) {
    clearInterval(state.speakingPrepTimerId);
    state.speakingPrepTimerId = null;
    renderSpeakingCueCard();
    return;
  }
  if (state.speakingPrepSeconds <= 0) state.speakingPrepSeconds = card.prep;
  state.speakingPrepTimerId = setInterval(() => {
    state.speakingPrepSeconds = Math.max(0, state.speakingPrepSeconds - 1);
    renderSpeakingCueCard();
    if (state.speakingPrepSeconds === 0) {
      clearInterval(state.speakingPrepTimerId);
      state.speakingPrepTimerId = null;
      showToast("准备时间结束，开始回答。");
    }
  }, 1000);
  renderSpeakingCueCard();
}

function renderSpeakingPersonalSource(card) {
  const pattern = card.part === "Part 1" ? /part.?1|p1|常考题型/i : card.part === "Part 2" ? /part.?2|p2|人物|地点|事件|物品/i : /part.?3|p3|成套刷题/i;
  renderPersonalSource({ selector: "[data-speaking-personal-source]", map: "speakingSourceMap", key: SPEAKING_SOURCE_MAP_KEY, item: card, title: "个人口语资料", label: card.part, selectLabel: "关联题卡", description: { selected: "看完后回到这张题卡录音。", empty: `已按 ${card.part} 筛选示例与技巧资料；关联后不会替代你的独立回答。` }, empty: "未找到可直接使用的口语资料。", candidates: personalSourceCandidates("speaking", ["preview", "stream"], pattern, 3), rerender: renderSpeakingCueCard });
}

function renderSpeakingCueCard() {
  const card = SPEAKING_CARDS[state.speakingCardIndex];
  document.querySelectorAll("[data-speaking-part]").forEach((button) => {
    const selected = Number(button.dataset.speakingPart) === state.speakingCardIndex;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  setText("[data-speaking-cue-meta]", `${card.part.toUpperCase()} · ${card.meta}`);
  setText("[data-speaking-cue-title]", card.title);
  setText("[data-speaking-cue-question]", card.question);
  setText("[data-speaking-prep-time]", speakingDuration(state.speakingPrepSeconds));
  const points = document.querySelector("[data-speaking-cue-points]");
  if (points) points.innerHTML = card.points.map((point) => `<li>${escapeHtml(point)}</li>`).join("");
  renderSpeakingPersonalSource(card);
  const button = document.querySelector("[data-speaking-prep]");
  if (button) button.textContent = !card.prep ? "无需准备" : state.speakingPrepTimerId ? "暂停准备" : state.speakingPrepSeconds < card.prep ? "继续准备" : "开始 60 秒准备";
}

function renderSpeakingRubric() {
  const session = activeSpeakingSession();
  const values = session.selfAssessment || { fluency: 5.5, lexical: 5.5, grammar: 5.5, pronunciation: 5.5 };
  const labels = { fluency: "流利连贯", lexical: "词汇", grammar: "语法", pronunciation: "发音" };
  const container = document.querySelector("[data-speaking-rubric]");
  if (container) container.innerHTML = Object.entries(labels).map(([key, label]) => `<label>${label}<input type="range" min="4" max="9" step="0.5" value="${values[key]}" data-speaking-rating="${key}"><output>${Number(values[key]).toFixed(1)}</output></label>`).join("");
  container?.querySelectorAll("[data-speaking-rating]").forEach((input) => input.addEventListener("input", () => { input.nextElementSibling.textContent = Number(input.value).toFixed(1); }));
}

function saveSpeakingSelfAssessment() {
  const session = activeSpeakingSession();
  const values = Object.fromEntries([...document.querySelectorAll("[data-speaking-rating]")].map((input) => [input.dataset.speakingRating, Number(input.value)]));
  session.selfAssessment = values;
  session.updatedAt = new Date().toISOString();
  persistSpeakingSessions();
  const average = Object.values(values).reduce((sum, value) => sum + value, 0) / 4;
  trackLearningEvent({ module: "Speaking", activity: "口语自评", durationMinutes: 2, sourceId: session.id, evidenceType: "self" });
  markAssessmentModule("Speaking", SPEAKING_CARDS[state.speakingCardIndex]?.id);
  setText("[data-speaking-rating-status]", `自评已保存：${(Math.round(average * 2) / 2).toFixed(1)}。建议下次只重点改善最低一项。`);
  renderToday();
}

function renderSpeakingMaterials() {
  const userText = activeSpeakingSession().turns.filter((turn) => turn.role === "user").map((turn) => turn.text).join(" ");
  const sentences = userText.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [];
  const useful = sentences.filter((sentence) => /\b(because|for example|however|although|therefore)\b/i.test(sentence)).slice(-3);
  const container = document.querySelector("[data-speaking-materials]");
  if (container) container.innerHTML = useful.length ? useful.map((sentence) => `<p>${escapeHtml(sentence.trim())}</p>`).join("") : "<p>回答中加入 because / for example 等展开表达后，会自动沉淀在这里。</p>";
}

function renderSpeakingComparison() {
  const container = document.querySelector("[data-speaking-compare]");
  const records = state.speakingCompareIds.map((id) => state.speakingRecordings.find((item) => item.id === id)).filter(Boolean).sort((a, b) => b.id - a.id);
  if (!container) return;
  container.hidden = records.length !== 2;
  if (records.length !== 2) return;
  const metrics = records.map((recording) => ({ duration: recording.duration, words: (recording.transcript?.match(/[A-Za-z]+/g) || []).length }));
  container.innerHTML = `<div class="section-title"><h2>录音对比</h2><span>较新 vs 较早</span></div><div><p><strong>${metrics[0].duration - metrics[1].duration >= 0 ? "+" : ""}${metrics[0].duration - metrics[1].duration}s</strong>回答时长</p><p><strong>${metrics[0].words - metrics[1].words >= 0 ? "+" : ""}${metrics[0].words - metrics[1].words}</strong>转写词数</p></div><small>时长和词数不等于分数；重点回听观点是否更完整、停顿是否更自然。</small>`;
}

function renderSpeakingCoach() {
  const session = activeSpeakingSession();
  const cardIndex = Number(session.cardIndex || 0);
  if (state.speakingCardIndex !== cardIndex) {
    state.speakingCardIndex = cardIndex;
    state.speakingPrepSeconds = SPEAKING_CARDS[cardIndex].prep;
  }
  renderSpeakingCueCard();
  renderSpeakingRubric();
  renderSpeakingMaterials();
  renderSpeakingComparison();
  renderSpeakingMode();
  const chat = document.querySelector("[data-speaking-chat]");
  if (!chat) return;
  chat.replaceChildren(...session.turns.map((turn) => {
    const bubble = document.createElement("article");
    bubble.className = `speaking-turn ${turn.role}${turn.pending ? " pending" : ""}`;
    const speaker = turn.role === "coach" ? (turn.ai ? "AI 考官" : "IELTS Teacher") : "You";
    bubble.innerHTML = `<span>${speaker}</span><p>${escapeHtml(turn.text)}</p>`;
    return bubble;
  }));
  chat.scrollTop = chat.scrollHeight;
}

function renderSpeakingMode() {
  document.querySelectorAll("[data-speaking-mode]").forEach((button) => {
    const selected = button.dataset.speakingMode === state.speakingMode;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  document.querySelectorAll("[data-speaking-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.speakingPanel !== state.speakingMode;
  });
  const card = SPEAKING_CARDS[state.speakingCardIndex];
  const modes = {
    conversation: ["对话", "看清题目后，按住录音按钮开始回答。", "开始回答"],
    review: ["复盘", "回听本轮回答，并完成四项自评。", "开始复盘"],
    history: ["历史", "回听、导出或修正以前的录音与转写。", "查看历史"],
  };
  renderPracticeStep("speaking", `${modes[state.speakingMode][0]} · ${card?.part || "Part"}`, card?.title, modes[state.speakingMode][1], modes[state.speakingMode][2]);
}

function appendSpeakingTurn(recording, transcript) {
  const session = activeSpeakingSession();
  transcript = String(transcript || "");
  const userText = transcript.trim() || `语音回答 · ${speakingDuration(recording.duration)}（等待转写）`;
  session.turns.push({ role: "user", text: userText, recordingId: recording.id, createdAt: recording.createdAt });
  const userTurns = session.turns.filter((turn) => turn.role === "user").length;
  const fallback = SPEAKING_FOLLOW_UPS[(userTurns - 1) % SPEAKING_FOLLOW_UPS.length];
  session.updatedAt = new Date().toISOString();
  recording.sessionId = session.id;
  recording.transcript = userText;
  persistSpeakingSessions();
  const wordCount = (transcript.match(/[A-Za-z]+/g) || []).length;
  const wordsPerMinute = recording.duration ? Math.round(wordCount / recording.duration * 60) : 0;
  const mistakeType = transcript && wordsPerMinute >= 90 ? "coherence" : "fluency";
  addWrongQuestion({
    id: `speaking-${recording.id}`,
    module: "Speaking",
    sessionId: session.id,
    title: "Speaking Part 1 · 回答复盘",
    sourceMaterial: session.title,
    userAnswer: transcript || "仅录音，等待转写",
    correctAnswer: "完整观点 + 具体例子",
    evidence: userText,
    mistakeType,
    aiExplanation: transcript
      ? `本轮约 ${wordsPerMinute} 词/分钟；下一轮优先保持自然节奏，并用 because / for example 展开观点。`
      : "本轮尚无转写；回听录音并补充文字后，再分析流利度与连贯性。",
    nextReviewDate: tomorrowIsoDate(),
    createdAt: recording.createdAt,
    status: "待复盘",
  });
  const useAiCoach = Boolean(transcript.trim()) && aiServiceReady();
  const coachTurn = {
    role: "coach",
    text: useAiCoach ? "AI 考官正在点评你的回答，大约需要 15 秒…" : fallback,
    createdAt: new Date().toISOString(),
    pending: useAiCoach,
  };
  session.turns.push(coachTurn);
  session.updatedAt = new Date().toISOString();
  persistSpeakingSessions();
  renderSpeakingCoach();
  if (useAiCoach) fillSpeakingCoachTurn(session.id, coachTurn.createdAt, fallback);
}

async function fillSpeakingCoachTurn(sessionId, turnCreatedAt, fallback) {
  const session = state.speakingSessions.find((item) => item.id === sessionId);
  const turn = session?.turns.find((item) => item.role === "coach" && item.pending && item.createdAt === turnCreatedAt);
  if (!session || !turn) return;
  const card = SPEAKING_CARDS[session.cardIndex] || SPEAKING_CARDS[0];
  const conversation = session.turns
    .filter((item) => !item.pending)
    .slice(-8)
    .map((item) => ({ role: item.role === "coach" ? "examiner" : "candidate", text: item.text }));
  try {
    const reply = await requestAI("speaking_coach", { card: { part: card.part, title: card.title, question: card.question }, conversation });
    if (!reply) throw new Error("empty speaking coach reply");
    turn.text = reply;
    turn.ai = true;
  } catch (error) {
    turn.text = `${fallback}（AI 考官暂时不可用，已改用本地追问。）`;
    console.warn("Speaking coach request failed", error);
  }
  turn.pending = false;
  session.updatedAt = new Date().toISOString();
  persistSpeakingSessions();
  if (state.activeSpeakingSessionId === sessionId) renderSpeakingCoach();
}

function renderSpeakingRecordings() {
  const list = document.querySelector("[data-speaking-history-list]");
  if (!list) return;
  state.speakingUrls.forEach(URL.revokeObjectURL);
  state.speakingUrls = [];

  const title = document.createElement("h2");
  title.textContent = `练习历史 · ${state.speakingRecordings.length}`;
  if (!state.speakingRecordings.length) {
    const empty = document.createElement("article");
    empty.className = "empty-state";
    empty.innerHTML = '<strong>还没有录音</strong><p>完成一次回答后，可在这里回听。</p><button data-empty-go="speaking" data-empty-mode="conversation">开始对话</button>';
    list.replaceChildren(title, empty);
    return;
  }

  list.replaceChildren(title, ...state.speakingRecordings.map((recording) => {
    const card = document.createElement("article");
    card.className = "speaking-recording";
    const url = URL.createObjectURL(recording.audio);
    state.speakingUrls.push(url);
    card.innerHTML = `
      <div><strong>${escapeHtml(recording.part ? `${recording.part} · ${recording.cardTitle || "题卡"}` : speakingDuration(recording.duration))}</strong><span>${speakingDuration(recording.duration)} · ${new Date(recording.createdAt).toLocaleString("zh-CN")}${recording.sourceMaterial ? ` · ${escapeHtml(recording.sourceMaterial)}` : ""}</span></div>
      <p>${escapeHtml(recording.transcript || "语音回答")}</p>
      <audio controls preload="metadata" src="${url}"></audio>
      <button type="button" data-speaking-compare-record="${recording.id}">${state.speakingCompareIds.includes(recording.id) ? "已选对比" : "加入对比"}</button>
      <button type="button" data-speaking-export-record="${recording.id}">导出录音</button>
      <button type="button" data-speaking-edit-record="${recording.id}">编辑转写</button>
      <label class="speaking-transcript-editor" hidden>转写文本<textarea rows="4" data-speaking-transcript-input="${recording.id}" placeholder="回听录音后补充或修正英文回答。">${escapeHtml(recording.transcript || "")}</textarea><button type="button" data-speaking-save-transcript="${recording.id}">保存转写</button></label>
    `;
    card.querySelector("[data-speaking-compare-record]").addEventListener("click", () => {
      const selected = state.speakingCompareIds.includes(recording.id);
      state.speakingCompareIds = selected ? state.speakingCompareIds.filter((id) => id !== recording.id) : [...state.speakingCompareIds.slice(-1), recording.id];
      renderSpeakingRecordings();
      renderSpeakingComparison();
      if (state.speakingCompareIds.length === 2) {
        state.speakingMode = "review";
        renderSpeakingMode();
      }
    });
    card.querySelector("[data-speaking-export-record]").addEventListener("click", () => exportSpeakingRecording(recording));
    card.querySelector("[data-speaking-edit-record]").addEventListener("click", (event) => {
      const editor = card.querySelector(".speaking-transcript-editor");
      editor.hidden = !editor.hidden;
      event.currentTarget.textContent = editor.hidden ? "编辑转写" : "取消编辑";
      if (!editor.hidden) editor.querySelector("textarea").focus();
    });
    card.querySelector("[data-speaking-save-transcript]").addEventListener("click", () => saveSpeakingTranscript(recording, card.querySelector("[data-speaking-transcript-input]").value));
    return card;
  }));
}

function exportSpeakingRecording(recording) {
  if (!(recording?.audio instanceof Blob)) return showToast("这条录音无法导出。", "error");
  const extension = recording.audio.type.includes("mp4") ? "m4a" : "webm";
  const date = new Date(recording.createdAt).toISOString().slice(0, 10);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(recording.audio);
  link.download = `ielts-os-speaking-${date}-${recording.id}.${extension}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 0);
  showToast("录音已导出。", "success");
}

async function saveSpeakingTranscript(recording, value) {
  const transcript = String(value || "").trim() || `语音回答 · ${speakingDuration(recording.duration)}（等待转写）`;
  recording.transcript = transcript;
  await saveSpeakingRecording(recording);
  const session = state.speakingSessions.find((item) => item.id === recording.sessionId);
  const turn = session?.turns.find((item) => item.recordingId === recording.id);
  if (turn) turn.text = transcript;
  if (session) {
    session.updatedAt = new Date().toISOString();
    if (!persistSpeakingSessions()) return showToast("转写已写入录音，但会话索引未能保存。", "error");
  }
  const wordsPerMinute = recording.duration ? Math.round((transcript.match(/[A-Za-z]+/g) || []).length / recording.duration * 60) : 0;
  const wrong = state.userWrongQuestions.find((item) => item.id === `speaking-${recording.id}`);
  if (wrong) {
    wrong.userAnswer = transcript;
    wrong.evidence = transcript;
    wrong.aiExplanation = `本轮约 ${wordsPerMinute} 词/分钟；回听时重点检查观点是否完整、停顿是否自然。`;
    persistUserWrongQuestions();
  }
  renderSpeakingRecordings();
  renderSpeakingCoach();
  showToast("转写已保存。", "success");
}

async function toggleSpeakingRecording() {
  if (state.speakingRecorder?.state === "recording") {
    state.speakingRecorder.stop();
    return;
  }

  if (!navigator.mediaDevices?.getUserMedia || !("MediaRecorder" in window)) {
    showToast("当前浏览器不支持录音，请在 iPhone App 中使用。");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!state.speakingPressActive) {
      stream.getTracks().forEach((track) => track.stop());
      setText("[data-speaking-status]", "按住按钮开始回答");
      return;
    }
    const mimeType = MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "";
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    state.speakingStream = stream;
    state.speakingRecorder = recorder;
    state.speakingStartedAt = Date.now();
    state.speakingTranscript = "";

    state.speakingNativeTranscribe = false;
    const nativeTranscriber = aiChatNative();
    if (nativeTranscriber) {
      try {
        ensureNativeTranscriptListener();
        await nativeTranscriber.startTranscribe();
        state.speakingNativeTranscribe = true;
      } catch (error) {
        console.warn("Native transcription unavailable", error);
      }
    }

    const Recognition = state.speakingNativeTranscribe ? null : window.SpeechRecognition || window.webkitSpeechRecognition;
    if (Recognition) {
      try {
        const recognition = new Recognition();
        recognition.lang = "en-US";
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.addEventListener("result", (event) => {
          state.speakingTranscript = Array.from(event.results).map((result) => result[0].transcript).join(" ");
          setText("[data-speaking-status]", state.speakingTranscript || "正在听…");
        });
        recognition.addEventListener("error", () => {});
        recognition.start();
        state.speakingRecognition = recognition;
      } catch (error) {
        console.warn("Speech recognition unavailable", error);
      }
    }

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) chunks.push(event.data);
    });
    recorder.addEventListener("stop", async () => {
      clearInterval(state.speakingTimerId);
      const duration = Math.max(1, Math.round((Date.now() - state.speakingStartedAt) / 1000));
      const recording = {
        id: Date.now(),
        createdAt: new Date().toISOString(),
        duration,
        audio: new Blob(chunks, { type: recorder.mimeType || "audio/webm" }),
        cardId: SPEAKING_CARDS[state.speakingCardIndex]?.id || "",
        cardTitle: SPEAKING_CARDS[state.speakingCardIndex]?.title || "口语题卡",
        part: SPEAKING_CARDS[state.speakingCardIndex]?.part || "",
        sourceMaterial: state.speakingSourceMap[SPEAKING_CARDS[state.speakingCardIndex]?.id]?.title || "",
      };
      try { state.speakingRecognition?.stop(); } catch (error) {}
      state.speakingRecognition = null;
      stream.getTracks().forEach((track) => track.stop());
      state.speakingRecorder = null;
      state.speakingStream = null;
      if (state.speakingNativeTranscribe) {
        try {
          const result = await aiChatNative()?.stopTranscribe();
          if (result?.text?.trim()) state.speakingTranscript = result.text.trim();
        } catch (error) { /* keep partial transcript from live events */ }
        state.speakingNativeTranscribe = false;
      }
      appendSpeakingTurn(recording, state.speakingTranscript);
      trackLearningEvent({ module: "Speaking", activity: "口语录音练习", durationMinutes: Math.max(1, duration / 60), sourceId: recording.sessionId, evidenceType: "practice" });
      markAssessmentModule("Speaking", SPEAKING_CARDS[state.speakingCardIndex]?.id);
      try {
        await saveSpeakingRecording(recording);
      } catch (error) {
        setText("[data-speaking-status]", "文字已保存，录音保存失败");
        setText("[data-speaking-record]", "按住说话");
        document.querySelector("[data-speaking-record]")?.setAttribute("aria-pressed", "false");
        renderSpeakingCoach();
        showToast("录音存储失败，但本轮对话文字已保留。");
        console.warn("Failed to save speaking recording", error);
        return;
      }
      state.speakingRecordings.unshift(recording);
      setText("[data-speaking-status]", "已保存，可回听");
      setText("[data-speaking-time]", speakingDuration(duration));
      setText("[data-speaking-record]", "按住说话");
      document.querySelector("[data-speaking-record]")?.setAttribute("aria-pressed", "false");
      renderSpeakingRecordings();
      renderSpeakingCoach();
      showToast("口语录音已保存在本机。");
      const transcriptReady = Boolean(state.speakingTranscript.trim());
      const words = (state.speakingTranscript.match(/[A-Za-z]+/g) || []).length;
      const expansions = (state.speakingTranscript.match(/\b(because|for example|for instance|however|therefore)\b/gi) || []).length;
      const focus = !transcriptReady ? "先回听并补充转写，再判断停顿和观点完整性。" : duration < 20 ? "回答较短，回听时检查是否包含观点、原因和例子。" : !expansions ? "回听时检查是否需要用原因或例子展开观点。" : "已出现展开表达，回听时重点检查停顿是否自然。";
      window.IELTSRemote?.showOutputDebrief?.({ module: "口语", headline: "回答已保存", meta: `${speakingDuration(duration)} · ${transcriptReady ? `${words} 个转写词` : "待补转写"}`, facts: [["回答时长", speakingDuration(duration)], ["展开表达", `${expansions} 处`]], focus, actionLabel: "回听并自评", target: "speaking", audio: recording.audio, transcript: transcriptReady ? state.speakingTranscript : "" });
    });

    recorder.start();
    setText("[data-speaking-status]", "正在录音，松开发送");
    setText("[data-speaking-record]", "松开发送");
    document.querySelector("[data-speaking-record]")?.setAttribute("aria-pressed", "true");
    state.speakingTimerId = setInterval(() => {
      setText("[data-speaking-time]", speakingDuration(Math.floor((Date.now() - state.speakingStartedAt) / 1000)));
    }, 1000);
  } catch (error) {
    showToast("无法使用麦克风，请在系统设置中允许 IELTS OS 访问。");
    console.warn("Microphone unavailable", error);
  }
}

function bindWritingControls() {
  document.querySelectorAll("[data-writing-type]").forEach((button) => button.addEventListener("click", () => {
    const task = state.writing?.tasks?.find((item) => item.type === button.dataset.writingType);
    if (!task) return;
    state.activeWritingTaskId = task.id;
    state.writingElapsedSeconds = Number(writingDraft(task.id).elapsedSeconds || 0);
    state.writingMode = "write";
    renderWriting();
  }));

  document.querySelectorAll("[data-writing-mode]").forEach((button) => button.addEventListener("click", () => {
    state.writingMode = button.dataset.writingMode || "write";
    renderWritingMode();
  }));

  document.querySelector("[data-writing-plan]")?.addEventListener("click", () => {
    const task = activeWritingTask();
    if (!task) return;
    const draft = writingDraft(task.id);
    draft.planVisible = !draft.planVisible;
    if (draft.planVisible) draft.guidanceUsed = true;
    draft.updatedAt = new Date().toISOString();
    if (!persistWritingDrafts()) return showToast("写作辅助状态未能保存，请释放存储空间后重试。", "error");
    renderWriting();
    if (draft.planVisible) showToast("已按提纲辅助练习记录；下一稿建议先独立列提纲。");
  });

  document.querySelector("[data-writing-text]")?.addEventListener("input", (event) => {
    const task = activeWritingTask();
    if (!task) return;
    const draft = writingDraft(task.id);
    draft.text = event.target.value;
    draft.elapsedSeconds = state.writingElapsedSeconds;
    draft.updatedAt = new Date().toISOString();
    const saved = persistWritingDrafts();
    renderWritingSubmitState(task, draft);
    renderWritingStructure(task, draft);
    setText("[data-writing-recovery]", saved ? "已自动保存到本机" : "自动保存失败，请释放存储空间后重试");
  });

  document.querySelector("[data-writing-notes]")?.addEventListener("input", (event) => {
    const task = activeWritingTask();
    if (!task) return;
    const draft = writingDraft(task.id);
    draft.notes = event.target.value;
    draft.updatedAt = new Date().toISOString();
    setText("[data-writing-recovery]", persistWritingDrafts() ? "写前思路与草稿已自动保存" : "自动保存失败，请释放存储空间后重试");
  });

  document.querySelector("[data-writing-timer]")?.addEventListener("click", toggleWritingTimer);
  document.querySelector("[data-writing-save]")?.addEventListener("click", () => {
    const task = activeWritingTask();
    if (!task) return;
    const draft = writingDraft(task.id);
    draft.elapsedSeconds = state.writingElapsedSeconds;
    draft.updatedAt = new Date().toISOString();
    if (!persistWritingDrafts()) return showToast("草稿未能保存，请释放存储空间后重试。", "error");
    renderWriting();
    showToast("草稿、写前思路和计时进度已保存在本机。", "success");
  });
  document.querySelector("[data-writing-submit]")?.addEventListener("click", submitWritingAnalysis);
}

function bindNavigation() {
  bindEdgeSwipeBack();
  bindWritingControls();
  document.querySelector("[data-startup-retry]")?.addEventListener("click", () => loadAppData(true));
  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-empty-go], [data-empty-reset]");
    if (!action) return;
    const reset = action.dataset.emptyReset;
    if (reset === "practice") {
      state.practiceSearch = "";
      state.practiceDifficulty = "全部";
      state.practiceStatus = "全部";
      state.practiceBook = "全部";
      state.practiceTest = "全部";
      state.practiceWrongOnly = false;
      state.practiceResourceFormat = "全部";
      state.practiceResourceAvailability = "全部";
      state.libraryLimit = 40;
      renderPractice();
      return;
    }
    if (reset === "word") {
      state.wordFilter = "全部";
      renderDailyWords();
      return;
    }
    if (reset === "wrong") {
      state.wrongModuleFilter = "全部";
      state.wrongQuestionTypeFilter = "全部";
      state.wrongTypeFilter = "全部";
      state.activeWrongId = null;
      state.wrongMode = "library";
      renderWrongQuestions();
      return;
    }
    const target = action.dataset.emptyGo;
    const mode = action.dataset.emptyMode;
    if (target === "writing") { state.writingMode = mode || "write"; renderWritingMode(); }
    if (target === "speaking") { state.speakingMode = mode || "conversation"; renderSpeakingMode(); }
    if (target === "reading") { state.readingMode = mode || "article"; renderReadingMode(); }
    showScreen(target);
  });

  document.querySelector("[data-practice-search]")?.addEventListener("input", (event) => {
    state.practiceSearch = event.target.value;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-practice-difficulty]")?.addEventListener("change", (event) => {
    state.practiceDifficulty = event.target.value;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-practice-book]")?.addEventListener("change", (event) => {
    state.practiceBook = event.target.value;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-practice-test]")?.addEventListener("change", (event) => {
    state.practiceTest = event.target.value;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-practice-resource-format]")?.addEventListener("change", (event) => {
    state.practiceResourceFormat = event.target.value;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-practice-resource-availability]")?.addEventListener("change", (event) => {
    state.practiceResourceAvailability = event.target.value;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-practice-wrong]")?.addEventListener("change", (event) => {
    state.practiceWrongOnly = event.target.checked;
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelectorAll("[data-practice-status]").forEach((button) => button.addEventListener("click", () => {
    state.practiceStatus = button.dataset.practiceStatus;
    renderPractice();
  }));
  document.querySelector("[data-practice-reset]")?.addEventListener("click", () => {
    state.practiceSearch = "";
    state.practiceDifficulty = "全部";
    state.practiceStatus = "全部";
    state.practiceBook = "全部";
    state.practiceTest = "全部";
    state.practiceWrongOnly = false;
    state.practiceResourceFormat = "全部";
    state.practiceResourceAvailability = "全部";
    state.libraryLimit = 40;
    renderPractice();
  });
  document.querySelector("[data-word-library-search]")?.addEventListener("input", (event) => {
    state.wordLibrarySearch = event.target.value;
    state.wordLibraryLimit = 80;
    renderWordLibrary();
  });
  document.querySelector("[data-word-library-more]")?.addEventListener("click", () => {
    state.wordLibraryLimit += 80;
    renderWordLibrary();
  });
  document.querySelector("[data-word-plan-daily]")?.addEventListener("input", (event) => renderWordPlan(event.target.value, true));
  document.querySelector("[data-save-word-plan]")?.addEventListener("click", saveWordPlan);

  document.querySelector("[data-run-health-check]")?.addEventListener("click", repairLearningEvents);
  document.querySelector("[data-refresh-storage]")?.addEventListener("click", renderStorageStatus);
  document.querySelector("[data-clear-temp-cache]")?.addEventListener("click", clearTemporaryStorage);
  document.querySelector("[data-clear-media-downloads]")?.addEventListener("click", clearMediaDownloads);
  document.querySelector("[data-clear-errors]")?.addEventListener("click", () => {
    removePersistedValue(ERROR_LOG_KEY);
    renderDataHealth();
    showToast("错误记录已清除。");
  });

  document.querySelectorAll("[data-onboarding-budget]").forEach((button) => button.addEventListener("click", () => {
    state.onboardingBudget = Number(button.dataset.onboardingBudget) || 60;
    document.querySelectorAll("[data-onboarding-budget]").forEach((item) => item.classList.toggle("selected", item === button));
  }));
  document.querySelector("[data-onboarding-start]")?.addEventListener("click", () => saveOnboardingProfile());
  document.querySelector("[data-onboarding-skip]")?.addEventListener("click", () => saveOnboardingProfile({ skipDiagnostic: true }));
  document.querySelector("[data-baseline-skip]")?.addEventListener("click", () => showScreen("today"));
  document.querySelector("[data-baseline-submit]")?.addEventListener("click", submitBaseline);

  document.querySelectorAll("[data-dashboard-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.dashboardRangeDays = Number(button.dataset.dashboardRange) === 30 ? 30 : 7;
      renderLearningDashboard();
    });
  });

  document.querySelectorAll("[data-open-sheet]").forEach((button) => {
    button.addEventListener("click", () => openSheet(button.dataset.openSheet));
  });

  document.querySelectorAll("[data-close-sheet]").forEach((button) => {
    button.addEventListener("click", closeSheets);
  });

  document.querySelectorAll("[data-resume-learning]").forEach((button) => button.addEventListener("click", (event) => {
    const target = event.currentTarget.dataset.resumeScreen || localStorage.getItem(LAST_SCREEN_KEY) || "word";
    showScreen(target, true);
    closeSheets();
  }));

  document.querySelectorAll("[data-open-writing-feedback]").forEach((button) => button.addEventListener("click", () => {
    state.writingMode = "feedback";
    renderWritingMode();
  }));
  document.querySelectorAll("[data-open-speaking-conversation]").forEach((button) => button.addEventListener("click", () => {
    state.speakingMode = "conversation";
    renderSpeakingMode();
  }));
  document.querySelectorAll("[data-open-wrong-library]").forEach((button) => button.addEventListener("click", () => {
    state.wrongMode = "library";
    renderWrongMode();
  }));
  document.querySelectorAll("[data-open-listening-study]").forEach((button) => button.addEventListener("click", () => {
    state.listeningMode = "study";
    renderListeningMode();
  }));
  document.querySelector("[data-ai-chat-mic]")?.addEventListener("click", () => startAiVoiceChat());
  document.querySelector("[data-ai-chat-end]")?.addEventListener("click", () => endAiVoiceChat(true));
  document.querySelector("[data-ai-live-toggle]")?.addEventListener("click", () => startAiVoiceChat());
  document.querySelector("[data-ai-live-finish]")?.addEventListener("click", () => endAiVoiceChat(true));
  document.querySelectorAll("[data-word-quiz-start]").forEach((button) => button.addEventListener("click", () => startWordQuiz(button.dataset.wordQuizStart)));
  document.querySelector("[data-word-quiz-next]")?.addEventListener("click", () => advanceWordQuiz());
  document.querySelector("[data-word-quiz-again]")?.addEventListener("click", () => startWordQuiz(state.wordQuiz.mode));
  document.querySelector("[data-ai-chat-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = event.currentTarget.querySelector("[data-ai-chat-text]");
    const text = String(input?.value || "").trim();
    if (!text) return;
    input.value = "";
    sendAiChatTurn(text);
  });
  document.querySelector("[data-agent-form]")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = event.currentTarget.querySelector("[data-agent-text]");
    const text = String(input?.value || "").trim();
    if (!text) return;
    input.value = "";
    sendAgentMessage(text);
  });
  document.querySelectorAll("[data-agent-chips] button").forEach((button) => {
    button.addEventListener("click", () => sendAgentMessage(button.textContent.trim()));
  });
  document.querySelector("[data-ai-plan]")?.addEventListener("click", () => sendAgentMessage("结合我最近听、说、读、写四科的练习、AI 复盘和错题，给出今天按优先级排列的训练计划，并说明每项依据。"));

  navButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const saveType = button.dataset.saveNote;
      if (saveType) {
        const item = currentWord();
        saveStatus.textContent =
          saveType === "ai"
            ? `已保存学习笔记：${item?.word || "当前词"} 的辨析与例句。`
            : `已保存到错题本：${item?.word || "当前词"} 已连接学习例句、同义替换和下次复习。`;
      }

      if (button.dataset.toast) showToast(button.dataset.toast);

      const target = button.dataset.go;
      if (target) {
        if (target === "detail") renderWordDetail();
        showScreen(target, button.matches('[aria-label^="返回"]'));
      }
    });
  });

  document.querySelectorAll("[data-toast]").forEach((button) => {
    button.addEventListener("click", () => showToast(button.dataset.toast));
  });

  document.querySelectorAll("[data-toggle-panel]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = document.querySelector(`[data-collapsible-panel="${button.dataset.togglePanel}"]`);
      if (!panel) return;
      const collapsed = panel.classList.toggle("is-collapsed");
      button.textContent = collapsed ? "展开" : "收起";
    });
  });

  document.querySelectorAll("[data-toggle-translation]").forEach((button) => {
    button.addEventListener("click", () => {
      if (state.examMode) return;
      if (!activePassage()?.paragraphs?.some((paragraph) => String(paragraph.translation || "").trim())) return;
      state.translationVisible = !state.translationVisible;
      renderReading();
      showToast(state.translationVisible ? "已展开全文翻译。" : "已隐藏全文翻译。");
    });
  });

  document.querySelectorAll("[data-exam-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.examMode = !state.examMode;
      if (state.examMode) {
        state.translationVisible = false;
        state.readingReviewVisible = false;
      }
      renderReading();
      showToast(state.examMode ? "已进入考试模式：隐藏翻译和点词。" : "已回到学习模式。");
    });
  });
  document.querySelector("[data-reading-timer]")?.addEventListener("click", toggleReadingTimer);
  document.querySelectorAll("[data-reading-mode]").forEach((button) => button.addEventListener("click", () => {
    state.readingMode = button.dataset.readingMode || "article";
    renderReadingMode();
  }));

  document.querySelectorAll("[data-reveal-definition]").forEach((button) => {
    button.addEventListener("click", revealCurrentWordDefinition);
  });
  document.querySelector("[data-word-known]")?.addEventListener("click", completeCurrentWord);
  document.querySelector("[data-word-continue]")?.addEventListener("click", continueAfterWordHint);

  document.querySelectorAll("[data-speak-current]").forEach((button) => {
    button.addEventListener("click", () => speakCurrentWord(button.dataset.speakCurrent));
  });

  document.addEventListener("click", (event) => {
    const lookupWord = event.target.closest("[data-lookup-word]");
    if (lookupWord) openWordLookup(lookupWord.dataset.lookupWord, lookupWord.dataset.sourceSentence);
  });

  document.querySelectorAll("[data-lookup-speak]").forEach((button) => {
    button.addEventListener("click", () => speakWord(state.lookupWord || currentWord()?.word, button.dataset.lookupSpeak));
  });

  document.querySelectorAll("[data-lookup-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.lookupDictionary = button.dataset.lookupTab || "shanbay";
      renderLookupDefinition();
    });
  });

  document.querySelectorAll("[data-listening-play]").forEach((button) => {
    button.addEventListener("click", () => {
      if (button.dataset.practicePrimary && state.listeningMode !== "study") return;
      const item = activeListeningItem();
      speakText(item?.audioScript, item?.title || "听力");
      button.textContent = "▶ 重新播放";
    });
  });

  document.querySelectorAll("[data-practice-primary]").forEach((button) => button.addEventListener("click", () => {
    const module = button.dataset.practicePrimary;
    if (module === "listening") {
      if (state.listeningMode !== "study") document.querySelector("[data-listening-task]")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (module === "reading") {
      const submitted = Boolean(currentAttempt()?.submitted || (currentAttempt()?.completed && currentAttempt()?.score));
      if (state.readingMode === "article" || (state.readingMode === "review" && !submitted)) {
        state.readingMode = "questions";
        renderReading();
      }
      document.querySelector(`[data-reading-panel="${state.readingMode}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (module === "writing") {
      document.querySelector(`[data-writing-panel="${state.writingMode}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      if (state.writingMode === "write") document.querySelector("[data-writing-text]")?.focus({ preventScroll: true });
      return;
    }
    const target = state.speakingMode === "conversation" ? ".speaking-recorder" : state.speakingMode === "review" ? ".speaking-self-review" : "[data-speaking-history-list]";
    document.querySelector(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));

  document.querySelector("[data-listening-transcript]")?.addEventListener("click", () => {
    if (!state.listeningTranscriptVisible) markListeningSentenceHint();
    state.listeningTranscriptVisible = !state.listeningTranscriptVisible;
    if (!state.listeningTranscriptVisible) state.listeningTranslationVisible = false;
    renderListening();
  });

  document.querySelector("[data-listening-translation]")?.addEventListener("click", () => {
    if (!String(activeListeningItem()?.audioScriptTranslation || "").trim()) return;
    if (!state.listeningTranslationVisible) markListeningSentenceHint();
    state.listeningTranslationVisible = !state.listeningTranslationVisible;
    if (state.listeningTranslationVisible) state.listeningTranscriptVisible = true;
    renderListening();
  });
  document.querySelector("[data-listening-sentence-play]")?.addEventListener("click", playListeningSentence);
  const moveListeningSentence = (index) => {
    if (index === state.listeningSentenceIndex) return;
    delete currentAttempt()?.dictationAppearances?.[state.listeningSentenceIndex];
    state.listeningSentenceIndex = index;
    window.speechSynthesis?.cancel();
    renderListeningSentence(activeListeningItem());
  };
  document.querySelector("[data-listening-prev]")?.addEventListener("click", () => moveListeningSentence(Math.max(0, state.listeningSentenceIndex - 1)));
  document.querySelector("[data-listening-next]")?.addEventListener("click", () => moveListeningSentence(Math.min(listeningSentences(activeListeningItem()).length - 1, state.listeningSentenceIndex + 1)));
  document.querySelector("[data-listening-loop]")?.addEventListener("click", () => {
    state.listeningSentenceLoop = !state.listeningSentenceLoop;
    renderListeningSentence(activeListeningItem());
    if (state.listeningSentenceLoop) playListeningSentence();
    else window.speechSynthesis?.cancel();
  });
  document.querySelectorAll("[data-listening-rate]").forEach((button) => button.addEventListener("click", () => {
    state.listeningSentenceRate = Number(button.dataset.listeningRate) || 0.88;
    renderListeningSentence(activeListeningItem());
  }));
  document.querySelector("[data-listening-dictation-check]")?.addEventListener("click", checkListeningDictation);
  document.querySelectorAll("[data-listening-mode]").forEach((button) => button.addEventListener("click", () => {
    state.listeningMode = button.dataset.listeningMode || "study";
    renderListeningMode();
  }));
  document.querySelector("[data-open-related-vocab]")?.addEventListener("click", () => {
    state.listeningVocabScene = activeListeningItem()?.vocabularyTopic || "全部";
    state.listeningVocabSearch = "";
    state.listeningVocabIndex = 0;
    state.listeningVocabResult = null;
    renderListeningVocabulary();
  });
  document.querySelector("[data-listening-vocab-play]")?.addEventListener("click", () => speakWord(activeListeningVocabularyWord()?.word));
  document.querySelector("[data-listening-vocab-check]")?.addEventListener("click", checkListeningVocabulary);
  document.querySelector("[data-listening-vocab-next]")?.addEventListener("click", nextListeningVocabulary);
  document.querySelector("[data-listening-vocab-answer]")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") state.listeningVocabResult ? nextListeningVocabulary() : checkListeningVocabulary();
  });
  document.querySelector("[data-listening-vocab-scene]")?.addEventListener("change", (event) => {
    state.listeningVocabScene = event.target.value;
    state.listeningVocabIndex = 0;
    state.listeningVocabResult = null;
    renderListeningVocabulary();
  });
  document.querySelector("[data-listening-vocab-search]")?.addEventListener("input", (event) => {
    state.listeningVocabSearch = event.target.value;
    state.listeningVocabIndex = 0;
    state.listeningVocabResult = null;
    renderListeningVocabulary();
  });

  document.querySelectorAll("[data-speaking-part]").forEach((button) => button.addEventListener("click", () => selectSpeakingCard(Number(button.dataset.speakingPart))));
  document.querySelector("[data-speaking-prep]")?.addEventListener("click", toggleSpeakingPrep);
  document.querySelector("[data-speaking-save-rating]")?.addEventListener("click", saveSpeakingSelfAssessment);
  document.querySelectorAll("[data-speaking-mode]").forEach((button) => button.addEventListener("click", () => {
    state.speakingMode = button.dataset.speakingMode || "conversation";
    renderSpeakingMode();
  }));

  const speakingButton = document.querySelector("[data-speaking-record]");
  if (speakingButton) {
    speakingButton.addEventListener("pointerdown", async (event) => {
      event.preventDefault();
      state.speakingPressActive = true;
      speakingButton.setPointerCapture?.(event.pointerId);
      if (state.speakingRecorder?.state !== "recording") await toggleSpeakingRecording();
    });
    speakingButton.addEventListener("pointerup", (event) => {
      event.preventDefault();
      state.speakingPressActive = false;
      if (state.speakingRecorder?.state === "recording") state.speakingRecorder.stop();
    });
    speakingButton.addEventListener("pointercancel", () => {
      state.speakingPressActive = false;
      if (state.speakingRecorder?.state === "recording") state.speakingRecorder.stop();
    });
    speakingButton.addEventListener("keydown", async (event) => {
      if (![' ', 'Enter'].includes(event.key) || event.repeat) return;
      event.preventDefault();
      state.speakingPressActive = true;
      if (state.speakingRecorder?.state !== "recording") await toggleSpeakingRecording();
    });
    speakingButton.addEventListener("keyup", (event) => {
      if (![' ', 'Enter'].includes(event.key)) return;
      event.preventDefault();
      state.speakingPressActive = false;
      if (state.speakingRecorder?.state === "recording") state.speakingRecorder.stop();
    });
  }
  document.querySelector("[data-speaking-new]")?.addEventListener("click", () => {
    state.activeSpeakingSessionId = null;
    state.speakingMode = "conversation";
    activeSpeakingSession();
    renderSpeakingCoach();
    showToast("已开始新的口语会话。");
  });

  document.querySelector("[data-wrong-module]")?.addEventListener("change", (event) => {
    state.wrongModuleFilter = event.target.value;
    state.activeWrongId = null;
    renderWrongQuestions();
  });
  document.querySelectorAll("[data-wrong-mode]").forEach((button) => button.addEventListener("click", () => {
    state.wrongMode = button.dataset.wrongMode || "today";
    renderWrongMode();
  }));
  document.querySelector("[data-wrong-question-type]")?.addEventListener("change", (event) => {
    state.wrongQuestionTypeFilter = event.target.value;
    state.activeWrongId = null;
    renderWrongQuestions();
  });
  document.querySelector("[data-wrong-type]")?.addEventListener("change", (event) => {
    state.wrongTypeFilter = event.target.value;
    state.activeWrongId = null;
    renderWrongQuestions();
  });

  document.querySelector("[data-open-library]")?.addEventListener("click", () => {
    state.practiceTab = "资料库";
    state.practiceSearch = "";
    renderPractice();
    showScreen("practice");
  });

  document.querySelector("[data-news-timer]")?.addEventListener("click", toggleNewsTimer);
  document.querySelector("[data-news-submit]")?.addEventListener("click", submitNewsReading);
  document.querySelector("[data-news-save-sentence]")?.addEventListener("click", saveNewsSentence);
  document.querySelector("[data-export-backup]")?.addEventListener("click", exportBackup);
  document.querySelector("[data-import-backup]")?.addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    if (file) importBackup(file);
    event.target.value = "";
  });
  document.querySelector("[data-undo-backup-import]")?.addEventListener("click", undoBackupImport);
  document.querySelector("[data-save-ai-endpoint]")?.addEventListener("click", () => {
    const value = document.querySelector("[data-ai-endpoint]")?.value.trim().replace(/\/$/, "") || "";
    if (value && !/^https?:\/\//.test(value)) {
      setText("[data-ai-status]", "请输入以 http:// 或 https:// 开头的服务地址。");
      return;
    }
    const previous = configuredAIEndpoint();
    const saved = value ? persistValue(AI_ENDPOINT_KEY, value) : removePersistedValue(AI_ENDPOINT_KEY);
    if (!saved) return setText("[data-ai-status]", "服务地址未能保存，请释放存储空间后重试。");
    if (value !== previous || !value) removePersistedValue(AI_VERIFIED_ENDPOINT_KEY);
    setText("[data-ai-status]", value ? "地址已保存；验证前使用本地规则，密钥只放服务端。" : "已使用本地规则，不生成 AI 评分。");
    renderAIAssistant();
  });
  document.querySelector("[data-test-ai-endpoint]")?.addEventListener("click", async (event) => {
    const endpoint = document.querySelector("[data-ai-endpoint]")?.value.trim().replace(/\/$/, "");
    if (!endpoint) {
      setText("[data-ai-status]", "请先填写服务地址。");
      return showToast("请先填写 AI 服务地址。", "error");
    }
    setButtonBusy(event.currentTarget, true, "测试中…");
    try {
      const response = await fetch(`${endpoint}/api/health`);
      const health = await response.json().catch(() => ({}));
      if (!response.ok || health.ok !== true) throw new Error("health failed");
      const provider = health.provider || "AI 服务";
      const model = health.model || "";
      if (!persistValue(AI_ENDPOINT_KEY, endpoint) || !persistValue(AI_VERIFIED_ENDPOINT_KEY, endpoint) || !persistValue(AI_PROVIDER_KEY, `${provider}${model ? ` · ${model}` : ""}`)) throw new Error("endpoint save failed");
      setText("[data-ai-status]", `${provider}${model ? ` · ${model}` : ""} 连接正常。`);
      showToast(`${provider} 服务连接正常。`, "success");
      renderAIAssistant();
    } catch (error) {
      if (localStorage.getItem(AI_VERIFIED_ENDPOINT_KEY) === endpoint) removePersistedValue(AI_VERIFIED_ENDPOINT_KEY);
      setText("[data-ai-status]", "AI 服务连接失败，请检查地址。");
      showToast("AI 服务连接失败。", "error");
      renderAIAssistant();
    } finally {
      setButtonBusy(event.currentTarget, false);
    }
  });
  document.querySelector("[data-save-reminder]")?.addEventListener("click", () => saveStudyReminder().catch(() => setText("[data-reminder-status]", "提醒设置失败，请检查系统权限。")));
  document.querySelector("[data-disable-reminder]")?.addEventListener("click", () => disableStudyReminder().catch(() => {}));
  document.querySelector("[data-assessment-review]")?.addEventListener("click", () => {
    if (state.assessmentSession && !state.assessmentSession.completedAt) finishAssessment();
    else {
      renderAssessment();
      trackLearningEvent({ module: "Review", activity: "阶段 Review", durationMinutes: 2, sourceId: localIsoDate() });
      showToast("阶段结论已按最新学习样本更新。");
    }
  });
  document.querySelector("[data-assessment-start]")?.addEventListener("click", startAssessment);
  document.querySelector("[data-assessment-full]")?.addEventListener("click", startFullMock);
  document.querySelectorAll("[data-plan-budget]").forEach((button) => {
    button.addEventListener("click", () => {
      state.dailyPlanBudget = Number(button.dataset.planBudget) || 60;
      persistValue(DAILY_PLAN_KEY, String(state.dailyPlanBudget));
      renderStudyPlan();
      renderToday();
    });
  });
  document.querySelectorAll("button[data-reflection-blocker]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("button[data-reflection-blocker]").forEach((item) => item.classList.toggle("selected", item === button));
  }));
  document.querySelectorAll("button[data-reflection-focus]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("button[data-reflection-focus]").forEach((item) => item.classList.toggle("selected", item === button));
  }));
  document.querySelector("[data-save-reflection]")?.addEventListener("click", saveDailyReflection);

  document.querySelectorAll("[data-add-wordbook]").forEach((button) => {
    button.addEventListener("click", saveLookupWord);
  });

  document.querySelectorAll("[data-add-current-word]").forEach((button) => {
    button.addEventListener("click", saveCurrentWord);
  });
  document.querySelectorAll("[data-add-current-later]").forEach((button) => {
    button.addEventListener("click", addCurrentWordToLater);
  });

  document.querySelectorAll("[data-word-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.wordFilter = button.dataset.wordFilter || "全部";
      renderDailyWords();
    });
  });

  document.querySelectorAll("[data-practice-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.dataset.practiceTab;
      state.practiceTab = tab;
      state.practiceSearch = "";
      state.practiceDifficulty = "全部";
      state.practiceStatus = "全部";
      state.practiceBook = "全部";
      state.practiceTest = "全部";
      state.practiceWrongOnly = false;
      state.practiceResourceFormat = "全部";
      state.practiceResourceAvailability = "全部";
      state.libraryLimit = 40;
      document.querySelector(".practice-filter-panel")?.removeAttribute("open");
      renderPractice();
      showToast(tab === "资料库" ? "已打开个人资料目录。" : `已切换到${tab}训练。`);
    });
  });

}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("./service-worker.js?v=95", { updateViaCache: "none" });
  } catch (error) {
    console.warn("Service worker registration failed", error);
  }
}

async function loadAppData(reload = false) {
  setStartupStatus("loading");
  try {
    const result = await IELTSReliability.loadDataSources(APP_DATA_SOURCES, (source) => loadJson(source.path, reload));
    state.startupMissing = result.missing;
    if (!result.ok) {
      const message = `核心学习内容未能读取（${result.missing.join(", ")}），请重新加载。`;
      setStartupStatus("error", message);
      recordClientError(message, "startup");
      return false;
    }
    Object.assign(state, result.values);
    state.reading = normalizeReadingOptions(state.reading);
    state.currentWordIndex %= Math.max(1, queueWords().length);
    state.activeWritingTaskId = state.writing.activeTaskId;
    state.writingElapsedSeconds = Number(writingDraft(state.activeWritingTaskId).elapsedSeconds || 0);
    state.activePracticeId = state.resumeState.activePracticeId || state.tests.activeItemId || state.activePracticeId;
    state.readingAnswers = currentAttempt()?.answers || {};
    window.IELTSRemote?.mountLibraryCenter?.(state, renderPractice, WEEKLY_GOALS, eventBand);
    renderToday();
    setStartupStatus("ready", "");
    showScreen(state.userProfile ? "today" : "onboarding");
    showToast(result.missing.length ? `${result.missing.length} 项扩展内容未加载，其余功能可正常使用。` : "学习内容已就绪。", result.missing.length ? "info" : "success");
    loadDailyReading();
    return true;
  } catch (error) {
    setStartupStatus("error", "核心学习内容未能读取（unknown），请重新加载。");
    recordClientError(error?.message || error, "startup");
    console.error(error);
    return false;
  }
}

function normalizeReadingOptions(reading) {
  if (!reading?.passages) return reading;
  for (const passage of reading.passages) {
    for (const question of passage.questions || []) {
      if (!question.options?.some((option) => typeof option === "string")) continue;
      const accepted = [question.answer, ...(question.aliases || [])].flat().map((value) => String(value).trim().toLowerCase());
      question.options = question.options.map((option) => typeof option === "string" ? { id: option, label: option, correct: accepted.includes(option.trim().toLowerCase()), feedback: question.aiExplanation || "请结合定位证据核对该选项。" } : option);
    }
  }
  return reading;
}

async function init() {
  setStartupStatus("loading");
  bindNavigation();
  const todayLabel = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "2-digit" })
    .formatToParts(new Date())
    .reduce((parts, item) => ({ ...parts, [item.type]: item.value }), {});
  setText("[data-current-date]", `${todayLabel.weekday} · ${todayLabel.month} ${todayLabel.day}`.toUpperCase());
  state.savedWords = loadSavedWords();
  state.userWrongQuestions = loadUserWrongQuestions();
  state.attempts = loadAttempts();
  state.wordProgress = loadWordProgress();
  state.writingDrafts = loadWritingDrafts();
  state.learningEvents = loadStoredArray(LEARNING_EVENTS_KEY);
  state.streak = loadStoredJson(STREAK_KEY, null, (value) => value === null || value && typeof value === "object" && !Array.isArray(value));
  migrateLegacySampleState();
  state.savedSentences = loadStoredArray(SAVED_SENTENCES_KEY);
  state.practiceFavorites = loadStoredArray(PRACTICE_FAVORITES_KEY);
  state.laterItems = loadStoredArray(LATER_ITEMS_KEY);
  state.resumeState = loadStoredJson(RESUME_STATE_KEY, { scrolls: {}, audioTimes: {} }, (value) => value && typeof value === "object" && !Array.isArray(value));
  state.resumeState.scrolls ||= {};
  state.resumeState.audioTimes ||= {};
  state.currentWordIndex = Number(state.resumeState.currentWordIndex || 0);
  state.readingElapsedSeconds = Number(state.resumeState.readingElapsedSeconds || 0);
  state.listeningSentenceIndex = Number(state.resumeState.listeningSentenceIndex || 0);
  state.listeningMode = state.resumeState.listeningMode === "test" ? "test" : "study";
  state.writingMode = ["write", "feedback", "history"].includes(state.resumeState.writingMode) ? state.resumeState.writingMode : "write";
  state.speakingMode = ["conversation", "review", "history"].includes(state.resumeState.speakingMode) ? state.resumeState.speakingMode : "conversation";
  state.wrongMode = ["today", "library", "detail"].includes(state.resumeState.wrongMode) ? state.resumeState.wrongMode : "today";
  state.readingMode = ["article", "questions", "review"].includes(state.resumeState.readingMode) ? state.resumeState.readingMode : "article";
  state.listeningVocabScene = state.resumeState.listeningVocabScene || "全部";
  state.listeningVocabIndex = Number(state.resumeState.listeningVocabIndex || 0);
  state.dailyPlanBudget = [30, 60, 90].includes(Number(localStorage.getItem(DAILY_PLAN_KEY))) ? Number(localStorage.getItem(DAILY_PLAN_KEY)) : 60;
  const isStoredObject = (value) => value && typeof value === "object" && !Array.isArray(value);
  const isStoredObjectOrNull = (value) => value === null || isStoredObject(value);
  state.userProfile = loadStoredJson(USER_PROFILE_KEY, null, isStoredObjectOrNull);
  state.baselineResult = loadStoredJson(BASELINE_RESULT_KEY, null, isStoredObjectOrNull);
  state.planAdjustments = loadStoredJson(PLAN_ADJUSTMENTS_KEY, {}, isStoredObject);
  state.planModules = loadStoredJson(PLAN_MODULES_KEY, {}, isStoredObject);
  state.assessmentSession = loadStoredJson(ASSESSMENT_SESSION_KEY, null, isStoredObjectOrNull);
  state.examWeek = loadStoredJson(EXAM_MODE_KEY, { checklist: {}, reflection: "", reflectionSavedAt: null }, isStoredObject);
  state.examWeek.checklist ||= {};
  state.dailyReflections = loadStoredJson(DAILY_REFLECTIONS_KEY, {}, isStoredObject);
  state.studyPathProgress = loadStoredJson(STUDY_PATH_PROGRESS_KEY, {}, isStoredObject);
  state.resourceProgress = loadStoredJson(RESOURCE_PROGRESS_KEY, {}, isStoredObject);
  state.listeningAuxMedia = loadStoredJson(LISTENING_AUX_MEDIA_KEY, {}, isStoredObject);
  state.listeningManualMap = loadStoredJson(LISTENING_MANUAL_MAP_KEY, {}, isStoredObject);
  state.readingSourceMap = loadStoredJson(READING_SOURCE_MAP_KEY, {}, isStoredObject);
  state.writingSourceMap = loadStoredJson(WRITING_SOURCE_MAP_KEY, {}, isStoredObject);
  state.speakingSourceMap = loadStoredJson(SPEAKING_SOURCE_MAP_KEY, {}, isStoredObject);
  state.recentResources = loadStoredArray(RECENT_RESOURCES_KEY);
  const reminderTime = localStorage.getItem(REMINDER_TIME_KEY);
  const reminderInput = document.querySelector("[data-reminder-time]");
  if (reminderTime && reminderInput) reminderInput.value = reminderTime;
  state.speakingSessions = loadStoredArray(SPEAKING_SESSIONS_KEY);
  state.aiMemory = loadStoredJson(AI_MEMORY_KEY, { dialogueSessions: [], speakingDebriefs: [], moduleReviews: [], agentHistory: [] }, isStoredObject);
  state.aiMemory.dialogueSessions = Array.isArray(state.aiMemory.dialogueSessions) ? state.aiMemory.dialogueSessions : [];
  state.aiMemory.speakingDebriefs = Array.isArray(state.aiMemory.speakingDebriefs) ? state.aiMemory.speakingDebriefs : [];
  state.aiMemory.moduleReviews = Array.isArray(state.aiMemory.moduleReviews) ? state.aiMemory.moduleReviews : [];
  state.aiMemory.agentHistory = Array.isArray(state.aiMemory.agentHistory) ? state.aiMemory.agentHistory : [];
  state.activeSpeakingSessionId = state.speakingSessions[0]?.id || null;
  await loadAppData();
  autoConfigureAIEndpoint().catch(() => {});
  pruneMediaDownloads().catch(() => {});
  registerServiceWorker();
}

init();
