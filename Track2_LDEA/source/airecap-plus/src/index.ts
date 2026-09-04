export type * from "./types.js";
export { DEFAULT_CONSTANTS, STRUCTURED_BIND_CONF, USER_BIND_CONF } from "./constants.js";
export {
  createStore,
  onEvent,
  replay,
  resetIdSeq,
  toJSONStore,
  type AggregatorOptions,
} from "./aggregator.js";
export { bindEvent, pathOverlapScore, unionScope, eventPaths } from "./bind.js";
export {
  computeConfidenceRaw,
  applyStatusClamp,
  recalcConfidence,
} from "./confidence.js";
export {
  DEFAULT_AIRECAP_DIR,
  appendEvents,
  initSession,
  listSessions,
  loadEventsFromFile,
  readEvents,
  readStore,
  rebuildStore,
  resolveRoot,
  sessionPaths,
  writeStore,
  type PersistPaths,
} from "./persist.js";
export {
  newEventId,
  nowIso,
  makeEvent,
  ingestGit,
  collectGitDiff,
  buildFileChangeEvent,
  parseGitNameStatus,
  parseGitNumstat,
  ingestTestOutput,
  parseTestOutput,
  parsePytest,
  parseVitest,
  buildTestResultEvent,
  ingestClaim,
  inferClaimHints,
  parseClaimKind,
  parseOutcomeType,
  type GitIngestMode,
  type GitIngestOptions,
  type GitRunner,
  type TestFramework,
  type TestIngestOptions,
  type ClaimIngestOptions,
} from "./ingest/index.js";
