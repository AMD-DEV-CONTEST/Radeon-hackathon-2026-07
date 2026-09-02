import { buildQuery, del, get, post, put } from "./client.js";


export const listChapters = (bookId, volumeId = null, languageCode = null) => (
  get(`/books/${encodeURIComponent(bookId)}/chapters`, {
    volume_id: volumeId,
    language_code: languageCode,
  })
);

export const createChapter = (bookId, payload) => (
  post(`/books/${encodeURIComponent(bookId)}/chapters`, payload)
);

export const getChapter = (chapterId) => get(`/chapters/${encodeURIComponent(chapterId)}`);

export const listChapterLocalizations = (chapterId) => (
  get(`/chapters/${encodeURIComponent(chapterId)}/localizations`)
);

export const createChapterLocalization = (chapterId, payload) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/localizations`, payload)
);

export const listTranslationModels = () => get("/translations/models");

export const createChapterTranslation = (chapterId, payload) => (
  post(
    `/chapters/${encodeURIComponent(chapterId)}/translations`,
    payload,
    { timeoutMs: 300_000 },
  )
);

export const listChapterTranslations = (chapterId) => (
  get(`/chapters/${encodeURIComponent(chapterId)}/translations`)
);

export const updateChapterTranslation = (translationId, payload) => (
  put(`/translations/${encodeURIComponent(translationId)}`, payload)
);

export const approveChapterTranslation = (translationId, sourceRevisionHash) => (
  post(`/translations/${encodeURIComponent(translationId)}/approve`, {
    expected_source_revision_hash: sourceRevisionHash,
  })
);

export const rejectChapterTranslation = (translationId) => (
  post(`/translations/${encodeURIComponent(translationId)}/reject`, {})
);

export const reviewChapterLocalization = (chapterId, action, sourceRevisionHash) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/translation-review`, {
    action,
    expected_source_revision_hash: sourceRevisionHash,
  })
);

export const saveChapter = (chapterId, payload) => (
  put(`/chapters/${encodeURIComponent(chapterId)}`, payload)
);

export const autosaveChapter = (chapterId, payload) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/autosave`, payload)
);

export const listChapterVersions = (chapterId) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/versions`, {})
);

export const analyzeChapter = (chapterId, analysisMode) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/analyze`, { analysis_mode: analysisMode })
);

export const buildChapterChangeSet = (chapterId) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/changeset`, {})
);

export const confirmLatestChapterChangeSet = (chapterId) => (
  post(`/chapters/${encodeURIComponent(chapterId)}/changeset/confirm`, {})
);

export const deleteChapter = (chapterId) => del(`/chapters/${encodeURIComponent(chapterId)}`);

// Kept for callers that still need the query-compatible create contract.
export const createChapterLegacy = (bookId, title, volumeId = null) => (
  post(`/books/${encodeURIComponent(bookId)}/chapters${buildQuery({ title, volume_id: volumeId })}`, {})
);
