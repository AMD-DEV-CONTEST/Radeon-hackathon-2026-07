# learning-integrity Specification

Defines the app's offline consistency, recoverable persistence, vocabulary scheduling, truthful learning signals, and release evidence.

#### Requirement: Offline asset and data consistency

The application MUST derive authoritative browser-script versions from `<script src="./NAME.js?v=N">`, require identical quoted URLs in `service-worker.js` `APP_SHELL`, and require the integer in `navigator.serviceWorker.register("./service-worker.js?v=N")` to equal `CACHE_NAME = "ielts-os-demo-vN"`. Runtime data discovery MUST accept literal `loadJson("./PATH")` calls or static `{ key, path, critical }` entries and MUST fail when it discovers zero sources. The exact runtime data inventory is `wordbook`, `practice`, `wrong-questions`, `reading`, `tests`, `listening`, `writing`, `synonyms`, `content-manifest`, `content-roadmap`, `audio-map`, `library-catalog`, and `study-paths`; every path MUST exist and appear in `APP_SHELL`.

Release parity MUST compare byte identity for exactly `index.html`, `app.js`, `styles.css`, `service-worker.js`, and `remote-update.js` across source, `dist`, and `ios/App/App/public`. It MUST additionally compare `app-reliability.js` after Batch B and `learning-core.js` after Batch C. Missing or mismatched applicable files, stale/mismatched versions, a missing shell/runtime path, an unshelled runtime dependency, or zero discovered sources MUST fail.

- Acceptance: `check:consistency` runs on real sources and four negative fixture mutations; `check-release-parity.mjs` verifies applicable source/build/iOS files and authoritative versions.

#### Requirement: Recoverable local persistence

Durable writes MUST include the values represented by `LAST_SCREEN_KEY`, `SAVED_SENTENCES_KEY`, `RESUME_STATE_KEY`, `REMINDER_TIME_KEY`, `PREIMPORT_BACKUP_KEY`, `DAILY_NEWS_CACHE_KEY`, `SAVED_WORDS_KEY`, `USER_WRONG_QUESTIONS_KEY`, `ATTEMPTS_KEY`, `WORD_PROGRESS_KEY`, `WRITING_DRAFTS_KEY`, `LEARNING_EVENTS_KEY`, `STREAK_KEY`, `SPEAKING_SESSIONS_KEY`, `PLAN_MODULES_KEY`, `DAILY_REFLECTIONS_KEY`, `PLAN_ADJUSTMENTS_KEY`, `EXAM_MODE_KEY`, `USER_PROFILE_KEY`, `DAILY_PLAN_KEY`, `BASELINE_RESULT_KEY`, `ASSESSMENT_SESSION_KEY`, `DAILY_WORD_QUEUE_KEY`, `READING_SOURCE_MAP_KEY`, `WRITING_SOURCE_MAP_KEY`, `SPEAKING_SOURCE_MAP_KEY`, `RECENT_RESOURCES_KEY`, `RESOURCE_PROGRESS_KEY`, `STUDY_PATH_PROGRESS_KEY`, `PRACTICE_FAVORITES_KEY`, `LATER_ITEMS_KEY`, `LISTENING_AUX_MEDIA_KEY`, `LISTENING_MANUAL_MAP_KEY`, `MEDIA_DOWNLOADS_KEY`, `AI_ENDPOINT_KEY`, and `AI_VERIFIED_ENDPOINT_KEY`, plus `remote-update.js` coach-stage, recovery-focus, plan-modules, stage-signature, and remote-manifest keys. Every such `setItem` MUST route through a function returning success/failure. Raw `setItem` is allowed only inside that gateway and for `ERROR_LOG_KEY`/`RECOVERY_KEY` best-effort logs wrapped in local `try/catch`.

Import's target boundary MUST be string-valued `BACKUP_KEYS` present in the payload; undo's boundary MUST be every key in the retained snapshot. Import MUST write `PREIMPORT_BACKUP_KEY` before changing a target. If that snapshot write fails, import MUST change zero target keys and show `无法创建导入前快照`. Each import or undo MUST capture immediate pre-operation string/null values. Any later failure MUST compensate every key changed during that operation to those immediate values. Compensation failure MUST show incomplete-restoration copy, retain the snapshot, and retain `{ operation: "import"|"undo", failedKeys: string[], createdAt: ISO_STRING }` with no learner text. Snapshot and marker MUST be removed only after every restoration succeeds; a later `undoBackupImport` MUST retry after storage is available.

Reflection, exam reflection, profile, plan, baseline, assessment session, word plan/progress, writing typing/submission, mappings, favorites/later/resources/path, media metadata, speaking transcript/rating/recording, AI endpoint, import, and undo callers MUST show success/autosave copy only when persistence returns true. Writing history MUST retain every full essay text without truncating old essays.

- Acceptance: `check:storage` enforces raw-write and caller inventories and executes snapshot abort, single-write failure, partial import, failed compensation, failed undo plus immediate-value compensation, marker/snapshot retention, successful retry, and essay retention.

#### Requirement: Browser backup lifetime

Browser/PWA JSON export MUST create a non-empty Blob, append its anchor to `document.body`, click it, remove it, and schedule exactly one object-URL revocation at 1000 ms. It MUST revoke zero times at 999 ms and exactly once after the scheduled 1000 ms callback.

- Acceptance: the production export adapter is run against a DOM and fake timer in `check:storage`.

#### Requirement: Critical and optional startup data

Critical sources MUST be `wordbook`, `practice`, `reading`, `tests`, `listening`, and `writing`. Optional fallbacks MUST be exactly: `wrongQuestions={items:[],notes:[]}`, `synonyms={groups:[],source:"",title:""}`, `contentManifest={version:0,records:[],description:""}`, `contentRoadmap={schemaVersion:0,books:[],stages:[],gaps:[],reservations:[]}`, `audioMap={version:0,items:[],policy:""}`, `libraryCatalog={schemaVersion:0,modules:[],personalCollections:[],totalResources:0,status:"partial"}`, and `studyPaths={version:0,paths:[]}`.

The missing list MUST contain every rejected source in source order. Mixed critical/optional failure MUST keep startup blocked, list all missing keys using `核心学习内容未能读取（KEYS），请重新加载。`, and MUST NOT commit optional fallbacks. Optional-only failure MUST allow normal startup and report `${COUNT} 项扩展内容未加载，其余功能可正常使用。`. Retry MUST call `loadAppData(true)` only. A successful retry MUST empty the missing list and prior error copy, remove `inert` and startup-hidden state from screens/navigation, hide the overlay, restore normal navigation, and leave the `bindNavigation` count at exactly one from initial `init`.

- Acceptance: `check:startup` executes all seven fallback shapes, all six critical classifications, mixed/optional-only/critical failure, exact copy, and retry DOM/handler cleanup.

#### Requirement: Same-day vocabulary relearning

Vocabulary states MUST be `new`, `learning`, `review`, and `relearning`; default ease MUST be 2.5. Every presentation MUST call `beginAppearance(word, appearanceId)` with a non-empty session-unique ID: `card:<session>:<serial>`, `quiz:<session>:<index>`, or `dictation:<session>:<index>`. Reveal/wrong MUST record failure at most once for the current ID; continuing/submitting that same appearance MUST NOT add another lapse. A later presentation MUST allocate a new ID and may add one lapse.

Legacy stage mapping MUST be missing/zero `reviewCount`→-1, 1–2→0, 3+→1. One failure MUST increment lapses once, set state `relearning`, stage 0, ease `max(1.3,ease-0.2)`, and `relearningDueDate=today`, while preserving prior `reviewDate` and `nextReviewDate`; leech MUST remain true once true or become true at six lapses. Unassisted success means the appearance has no failure/reveal flag: it MUST set state `review`, write `reviewDate=today`, clear relearning due, preserve leech/ease, leave a relearning word at stage 0, and otherwise advance stage by one to maximum 8.

Stages MUST index `[1,2,4,8,16,35,70,140,240]`. Jitter MUST be `0.95 + random*0.10`; interval MUST be `max(1,round(intervals[stage]*ease/2.5*jitter))`; next date MUST be today plus interval.

- Acceptance: `check:word-scheduler` drives helper transitions and real card/quiz/dictation adapters, including ID uniqueness/reuse/new-allocation and failure idempotence.

#### Requirement: Bounded honest vocabulary workload

Backlog MUST contain selected-book words not completed today that are relearning, have progress with missing or `<=today` next date, or have no progress with static `memoryState="due"`. Ordering MUST be relearning first, lapses descending, missing date as `0000-00-00` then date ascending, stage ascending, and `bookIndex` ascending. Daily new MUST normalize to integer 1–200 with invalid/zero→8. Cap MUST be `max(40,daily*6)` and review slots `floor(cap*0.8)`. Reviews MUST take the first review slots. Fresh MUST always take the first `min(daily,cap-reviewCount)` unseen book-order words, even while review backlog exists. Same-day retries MUST use only remaining presentation capacity and otherwise remain relearning for the next day. `deferredReview` MUST equal `backlog.length-reviewCount`; `deferred` MUST equal `deferredReview+(unseenCandidateCount-freshCount)`. Queue construction MUST NOT mutate progress dates. When `deferredReview>0`, the existing `[data-word-plan-today]` summary MUST append `；另有 N 个到期复习延后` using that exact count.

Projection MUST return whole days `ceil(remainingUnseen/normalizedDaily)+ceil(deferredReview/max(1,reviewSlots))`. The UI MUST call 400 days only the no-backlog lower bound.

The deterministic oracle MUST start 2026-01-01 with one synthetic `ielts-core` corpus of 8000 words numbered 1–8000, empty progress/queue, daily new 20, random 0.5, and no static due seeds. Until all words are introduced, a global attempt index MUST advance on every fresh/review/relearning presentation; residues 5/11/17 modulo 20 fail and all others succeed. Introduction occurs only on first success. By day 730 all words MUST be introduced and no day may exceed 120 presentations; actual deferred review MUST remain visible. After all introductions, the recovery phase MUST answer every remaining review correctly and reduce deferred review to <=120 by day 3000, with deferred review non-increasing over the final 30 days.

- Acceptance: `check:word-scheduler` asserts formulas, ordering, date immutability, projection, and the exact oracle.

#### Requirement: Truthful streak and band signals

A streak event MUST be persisted, have duration >0, and exclude `activity="首次基线诊断"`. A valid stored streak MUST have integer count >=1 and a real local `YYYY-MM-DD` not after today; valid storage wins migration. Otherwise derive contiguous qualifying dates ending today or yesterday. Same day MUST be idempotent, next day MUST add one, a gap MUST reset to one, and no qualifying events MUST return null.

Explicit assessment averaging MUST require four finite Listening/Reading/Writing/Speaking values and return their arithmetic mean rounded to 0.5; incomplete input MUST return null.

Calibration MUST reject baseline and `maxScore<=0`. Listening/Reading MUST accept `evidenceType="objective"` or a legacy source ID matching `^(listening|reading)-\d+-\d+-\d+` with `maxScore>=10`; Writing/Speaking MUST accept only `evidenceType="verified"`. It MUST sort newest first and select at most eight. Readiness MUST require at least two selected events and, for Listening/Reading, selected maxScore sum >=20. If any selected direct `maxScore=9` event exists, scoring MUST ignore non-direct events and weight direct newest-first N..1. Otherwise it MUST average selected `score/maxScore` and map >=.9→8, >=.8→7.5, >=.7→6.5, >=.6→6, >=.5→5.5, >=.4→5, else 4.5. Summary MUST average ready module scores in Listening/Reading/Writing/Speaking order to nearest 0.5; zero ready MUST return null. Both `app.js` and `remote-update.js` MUST consume this one helper policy and MUST NOT keep duplicate thresholds.

Queue counts MUST be `fresh=freshNames.length`, `review=total-fresh`, with pending fields excluding `reviewDate=today`; `pending=pendingFresh+pendingReview`; completion MUST be `total>0 && pending===0`. If yesterday's valid focus is absent from ranked distinct modules, it MUST replace the third; fewer than three MUST retain every available module.

- Acceptance: `check:learning-signals` asserts streak, explicit average, calibration 0/1/2/4 coverage, queue/focus formulas, source de-duplication, and `remote-update.js` rendered-output parity with the helper.

#### Requirement: Release and handoff evidence

Package commands MUST remain exactly `check:consistency=node scripts/check-consistency.mjs`, `check:storage=node scripts/check-storage-recovery.mjs`, `check:startup=node scripts/check-startup-resilience.mjs`, `check:word-scheduler=node scripts/check-word-scheduler.mjs`, `check:learning-signals=node scripts/check-learning-signals.mjs`, and `check:status-handoff=node scripts/check-status-handoff.mjs`. The first five MUST remain in aggregate `npm run check`; status MUST remain separate.

Versions MUST be baseline/A app73/cache90; B app74/cache91/reliability1; C app75/cache92/reliability1/learning1; D app76/cache93/reliability1/learning2; E app77/cache94/styles59/remote17; and F app78/cache95/styles60/remote18. Each batch MUST run its focused checks, aggregate check, build, `npx cap sync ios`, release parity, status update, and separate status check. Any required failure MUST stop the batch.

Status MUST preserve historical v73/baseline evidence, set the local verification date, support `Optimization batch: A-consistency|B-storage-startup|C-word-scheduler|D-learning-signals|E-navigation-scroll|F-production-polish`, record exact current versions and actual phone install/launch state, include three PASSED release lines plus MATCHED parity, and include the matching completed breakpoint label. Batch F MUST record browser polish evidence and set the next task to real-device v78 verification followed by remaining content/audio work. A connected but locked or unavailable phone MUST be recorded honestly and MUST NOT turn a successful local code batch into a false device pass.

- Acceptance: focused checks, `npm run check`, `npm run build`, `npx cap sync ios`, `node scripts/check-release-parity.mjs`, updated status, and `npm run check:status-handoff` execute in order; status rejects absent, stale, or contradictory fields.

#### Requirement: Root navigation clarity

Bottom-tab root screens MUST NOT expose a return control. Existing nested return controls MUST remain, and the shared left-edge gesture MUST continue to activate only those controls and restore the saved parent scroll position.

#### Requirement: Recoverable existing AI setup

When the AI service is not verified, the existing voice action MUST route to Settings; when verified it MUST retain the existing voice-dialogue behavior.

#### Requirement: Settings information order

The existing open Content/iCloud group MUST appear before the existing content-update card. All reminder, AI endpoint, backup, storage, and health controls MUST remain present.

#### Requirement: Natural product copy and readable secondary text

Product-owned UI descriptions MUST use direct Chinese and preserve factual limitations. Imported/learner/model content MUST remain unchanged. Rejected assistant-like patterns MUST be absent, a fresh reviewer MUST score at least 45/50, and the active muted/surface contrast MUST be at least 4.5:1.

The review corpus MUST be every changed Chinese UI string in `index.html`, `app.js`, and `remote-update.js`, recorded with a reproducible corpus hash. The independent review MUST record reviewer identity, that hash, 1-10 scores for directness/rhythm/trust/authenticity/concision, and at least one changed example per dimension; total MUST be >=45/50.

The unverified AI setup action MUST remain enabled. At 390×844, Today, Learning, AI, Wrong Book, Profile, and Settings MUST render without clipping or overlap.

#### Requirement: Fail-closed iPhone reinstall

The reinstall script MUST sync, build/sign with Xcode into deterministic `-derivedDataPath "${TMPDIR:-/tmp}/ielts-os-derived-data"`, verify and install the exact resulting `Build/Products/Debug-iphoneos/App.app`, verify the app and nested CDHashes, install, launch, and verify the process. Normal mode MUST use incremental `build`; `--rebuild` MUST use `clean build`. It MUST return non-zero when any required gate fails and MUST NOT mask those failures.

#### Requirement: Protected learning behavior

This batch MUST NOT change files under `data/` or `content-packs/`, `learning-core.js`, or `app-reliability.js`; storage keys, backup boundaries, scheduling/scoring formulas, and content records MUST remain unchanged. Focused storage, scheduler, learning-signal, content-quality, and API checks plus the aggregate suite MUST pass.
