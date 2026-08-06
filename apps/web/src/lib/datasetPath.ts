/**
 * Encode a dataset id for URL paths when it may be ``owner/name`` (HF style).
 * Do **not** wrap the whole id in ``encodeURIComponent`` — that turns ``/``
 * into ``%2F`` and many servers treat it as a single path segment, breaking
 * routes that expect real slashes between ``owner`` and ``name``.
 */
export function encodeDatasetPath(datasetId: string): string {
  return datasetId.split('/').map((seg) => encodeURIComponent(seg)).join('/')
}
