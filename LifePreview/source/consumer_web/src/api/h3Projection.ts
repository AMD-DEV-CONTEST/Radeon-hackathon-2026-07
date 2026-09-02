export type ReferenceViewName = "front" | "three_quarter_left" | "profile_left";

export interface H3ReferenceCard {
  referenceSetId: string;
  referenceSetRevisionId: string;
  characterId: string;
  ageStage: string;
  viewName: ReferenceViewName;
  attemptOrdinal: 0 | 1;
  imageUrl: string;
  qcPassed: true;
  modelFamily: "flux2-dev";
  modelId: "flux2-dev-fp8mixed.v1";
  revision: "flux2-dev-fp8mixed.v1";
}

export interface H3QcVector {
  mediaIntegrity: number;
  identityAndSemantics: number;
  technicalQuality: number;
  aestheticQuality: number;
}

export interface H3AttemptProjection {
  attemptOrdinal: 0 | 1;
  qcVector: H3QcVector;
  exceptionCodes: string[];
}

export interface H3SequenceProjection {
  sequenceId: string;
  ordinal: number;
  durationSeconds: number;
  status: "delivered";
  attempts: H3AttemptProjection[];
  selectedAttemptOrdinal: 0 | 1;
  selectedCleanly: boolean;
  selectedWithQcException: boolean;
  exceptionCodes: string[];
  selectionReason: string;
}

export type H3Disclosure =
  | {
      code: "SOURCE_GROUNDED";
      contentMode: "source_grounded";
      label: string;
      notice: string;
    }
  | {
      code: "AI_COMPLETED_NON_ORIGINAL";
      contentMode: "ai_completed";
      label: string;
      notice: string;
    };

export interface H3ProductProjection {
  schemaVersion: "shidu.h3-product-projection.v1";
  episodeRevisionId: string;
  projectId: string;
  status: "succeeded";
  durationSeconds: number;
  referenceCards: H3ReferenceCard[];
  sequences: H3SequenceProjection[];
  playbackUrl: string;
  downloadUrl: string;
  disclosure: H3Disclosure;
}

export interface H3ProjectionParseOptions {
  httpsHostAllowlist?: readonly string[];
}

const PROJECTION_SCHEMA = "shidu.h3-product-projection.v1" as const;
const FLUX_MODEL_FAMILY = "flux2-dev" as const;
const FLUX_MODEL_ID = "flux2-dev-fp8mixed.v1" as const;
const CANONICAL_VIEWS: readonly ReferenceViewName[] = [
  "front",
  "three_quarter_left",
  "profile_left",
];
const QC_FIELDS: readonly (keyof H3QcVector)[] = [
  "mediaIntegrity",
  "identityAndSemantics",
  "technicalQuality",
  "aestheticQuality",
];
const FORBIDDEN_PUBLIC_TEXT = [
  ".safetensors",
  "/persistent",
  "/workspace",
  "comfyui",
  ".srt",
  ".vtt",
  "subtitle",
  "gpu",
];
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const SAFE_SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._~-]*$/;
const DNS_HOST = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

type JsonObject = Record<string, unknown>;

export class H3ProjectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "H3ProjectionError";
  }
}

function fail(message: string): never {
  throw new H3ProjectionError(message);
}

function objectValue(value: unknown, field: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(`${field} must be an object`);
  }
  return value as JsonObject;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) fail(`${field} must be an array`);
  return value;
}

function exactKeys(value: JsonObject, expected: readonly string[], field: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    fail(`${field} contains fields outside the Python DTO whitelist`);
  }
}

function stringValue(value: unknown, field: string, maxLength = 500): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > maxLength) {
    fail(`${field} must be a non-empty string`);
  }
  return value;
}

function literal<T extends string>(value: unknown, expected: T, field: string): T {
  if (value !== expected) fail(`${field} must equal ${expected}`);
  return expected;
}

function identifierValue(value: unknown, field: string): string {
  const identifier = stringValue(value, field, 160);
  if (!IDENTIFIER.test(identifier)) fail(`${field} must be a logical identifier`);
  return identifier;
}

function uuidValue(value: unknown, field: string): string {
  const uuid = stringValue(value, field, 36);
  if (!UUID_PATTERN.test(uuid)) fail(`${field} must be a canonical UUID`);
  return uuid;
}

function integerValue(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    fail(`${field} must be an integer`);
  }
  return value;
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    fail(`${field} must be a finite number`);
  }
  return value;
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") fail(`${field} must be a boolean`);
  return value;
}

function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function decodeRepeated(value: string, field: string): string {
  let decoded = value;
  for (let index = 0; index < 4; index += 1) {
    let next: string;
    try {
      next = decodeURIComponent(decoded);
    } catch {
      fail(`${field} contains malformed URL encoding`);
    }
    if (next === decoded) return decoded;
    decoded = next;
  }
  fail(`${field} contains excessive nested encoding`);
}

function publicText(value: unknown, field: string): string {
  const text = stringValue(value, field);
  const decoded = decodeRepeated(text, field);
  const lowered = decoded.toLocaleLowerCase();
  if (
    decoded.includes("\\")
    || /(?:^|[\s(（])[A-Za-z]:[\\/]/.test(decoded)
    || /(?:^|[\s(（])\/(?:[A-Za-z0-9._~-]+\/)*[A-Za-z0-9._~-]+/.test(decoded)
    || /\b(?:file|https?|s3|gs|ftp):/i.test(decoded)
    || FORBIDDEN_PUBLIC_TEXT.some((marker) => lowered.includes(marker))
  ) {
    fail(`${field} public text contains a file path or URI`);
  }
  return text;
}

function normalizedAllowlist(values: readonly string[]): ReadonlySet<string> {
  const hosts = new Set<string>();
  for (const value of values) {
    const rawHost = stringValue(value, "httpsHostAllowlist[]", 253);
    if (rawHost !== rawHost.trim() || /[/\\@#?]/.test(rawHost)) {
      fail("HTTPS allowlist entries must be hostnames without URL syntax");
    }
    const host = canonicalHost(rawHost, "httpsHostAllowlist[]");
    if (!host.includes(":") && !/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host) && !host.includes(".")) {
      fail("HTTPS allowlist entry must be a public DNS name or IP address");
    }
    hosts.add(host);
  }
  return hosts;
}

function parseIpv6(host: string): number[] | null {
  let text = host.toLocaleLowerCase().replace(/^\[|\]$/g, "");
  if (text.includes(".")) {
    const lastColon = text.lastIndexOf(":");
    const dotted = text.slice(lastColon + 1);
    const parts = dotted.split(".");
    if (
      lastColon < 0
      || parts.length !== 4
      || parts.some((part) => !/^\d{1,3}$/.test(part) || Number(part) > 255)
    ) return null;
    const octets = parts.map(Number);
    text = `${text.slice(0, lastColon)}:${(
      (octets[0] << 8) | octets[1]
    ).toString(16)}:${((octets[2] << 8) | octets[3]).toString(16)}`;
  }
  const halves = text.split("::");
  if (halves.length > 2) return null;
  const parseHalf = (half: string): number[] | null => {
    if (half === "") return [];
    const groups = half.split(":");
    if (groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) return null;
    return groups.map((group) => Number.parseInt(group, 16));
  };
  const left = parseHalf(halves[0]);
  const right = parseHalf(halves[1] ?? "");
  if (left === null || right === null) return null;
  if (halves.length === 1) return left.length === 8 ? left : null;
  const omitted = 8 - left.length - right.length;
  if (omitted < 1) return null;
  return [...left, ...Array<number>(omitted).fill(0), ...right];
}

function canonicalIpv6(words: readonly number[]): string {
  let bestStart = -1;
  let bestLength = 0;
  for (let start = 0; start < words.length;) {
    if (words[start] !== 0) {
      start += 1;
      continue;
    }
    let end = start;
    while (end < words.length && words[end] === 0) end += 1;
    if (end - start > bestLength && end - start >= 2) {
      bestStart = start;
      bestLength = end - start;
    }
    start = end;
  }
  const groups = words.map((word) => word.toString(16));
  if (bestStart < 0) return groups.join(":");
  const left = groups.slice(0, bestStart).join(":");
  const right = groups.slice(bestStart + bestLength).join(":");
  return `${left}::${right}`;
}

function canonicalHost(value: string, field: string): string {
  let host = value.toLocaleLowerCase();
  if (host.endsWith(".")) host = host.slice(0, -1);
  if (host.startsWith("[") || host.endsWith("]")) {
    if (!(host.startsWith("[") && host.endsWith("]"))) {
      fail(`${field} hostname is malformed`);
    }
    host = host.slice(1, -1);
  }
  if (host.includes(":")) {
    const words = parseIpv6(host);
    if (words === null) fail(`${field} hostname is malformed`);
    return canonicalIpv6(words);
  }
  const ipv4Parts = host.split(".");
  if (ipv4Parts.length === 4 && ipv4Parts.every((part) => /^\d{1,3}$/.test(part))) {
    if (ipv4Parts.some((part) => part.length > 1 && part.startsWith("0"))) {
      fail(`${field} hostname is malformed`);
    }
    const octets = ipv4Parts.map(Number);
    if (octets.some((octet) => octet > 255)) fail(`${field} hostname is malformed`);
    return octets.join(".");
  }
  if (!host || !DNS_HOST.test(host)) fail(`${field} hostname is malformed`);
  return host;
}

function privateIpv4(host: string): boolean {
  const parts = host.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^\d{1,3}$/.test(part))) return false;
  const octets = parts.map(Number);
  if (octets.some((octet) => octet > 255)) return true;
  const [first, second, third, fourth] = octets;
  return first === 0
    || first === 10
    || (first === 100 && second >= 64 && second <= 127)
    || first === 127
    || (first === 169 && second === 254)
    || (first === 172 && second >= 16 && second <= 31)
    || (
      first === 192
      && second === 0
      && ((third === 0 && fourth !== 9 && fourth !== 10) || third === 2)
    )
    || (first === 192 && second === 168)
    || (first === 198 && (second === 18 || second === 19))
    || (first === 198 && second === 51 && third === 100)
    || (first === 203 && second === 0 && third === 113)
    || first >= 224;
}

function ipv6Value(words: readonly number[]): bigint {
  return words.reduce((value, word) => (value << 16n) | BigInt(word), 0n);
}

function inIpv6Cidr(value: bigint, prefix: string, bits: number): boolean {
  const words = parseIpv6(prefix);
  if (words === null) return false;
  const shift = BigInt(128 - bits);
  return (value >> shift) === (ipv6Value(words) >> shift);
}

function privateIpv6(host: string): boolean {
  const words = parseIpv6(host);
  if (words === null) return true;
  if (
    words.slice(0, 5).every((word) => word === 0)
    && words[5] === 0xffff
  ) {
    const ipv4 = [
      words[6] >> 8,
      words[6] & 0xff,
      words[7] >> 8,
      words[7] & 0xff,
    ].join(".");
    return privateIpv4(ipv4);
  }

  const value = ipv6Value(words);
  if ((words[0] & 0xe000) !== 0x2000) return true;
  if (
    inIpv6Cidr(value, "2001:db8::", 32)
    || inIpv6Cidr(value, "2002::", 16)
    || inIpv6Cidr(value, "3fff::", 20)
  ) return true;
  if (inIpv6Cidr(value, "2001::", 23)) {
    const publicExceptions = [
      ["2001:1::1", 128],
      ["2001:1::2", 128],
      ["2001:1::3", 128],
      ["2001:3::", 32],
      ["2001:4:112::", 48],
      ["2001:20::", 28],
      ["2001:30::", 28],
    ] as const;
    return !publicExceptions.some(([prefix, bits]) => inIpv6Cidr(value, prefix, bits));
  }
  return false;
}

function privateHost(host: string): boolean {
  const lowered = host.toLocaleLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (
    lowered === "localhost"
    || [".localhost", ".local", ".internal", ".lan"].some((suffix) => lowered.endsWith(suffix))
  ) return true;
  if (privateIpv4(lowered) || /^\d+$/.test(lowered)) return true;
  if (lowered.includes(":")) {
    return privateIpv6(lowered);
  }
  return false;
}

function validatePath(path: string, field: string, artifactsOnly: boolean): string {
  if (!path.startsWith("/") || path.includes("//")) {
    fail(`${field} URL path is not canonical`);
  }
  let segments = path.slice(1).split("/");
  if (artifactsOnly) {
    if (segments[0] !== "artifacts") {
      fail(`${field} URL must use /artifacts/<safe segments>`);
    }
    segments = segments.slice(1);
  }
  if (
    segments.length === 0
    || segments.some((segment) => (
      segment === "" || segment === "." || segment === ".." || !SAFE_SEGMENT.test(segment)
    ))
  ) {
    fail(`${field} URL contains an unsafe path segment`);
  }
  return path;
}

function rejectNonCanonicalNumericAuthority(url: string, field: string): void {
  const match = /^https:\/\/([^/?#]+)/i.exec(url);
  if (match === null) return;
  const authority = match[1].slice(match[1].lastIndexOf("@") + 1);
  if (authority.startsWith("[")) return;
  const rawHost = authority.split(":", 1)[0].toLocaleLowerCase();
  const numericParts = rawHost.split(".");
  if (
    /^\d+$/.test(rawHost)
    || /^0x[0-9a-f]+$/.test(rawHost)
    || numericParts.some((part) => /^0x/i.test(part))
    || (
      numericParts.length === 4
      && numericParts.every((part) => /^\d+$/.test(part))
      && numericParts.some((part) => part.length > 1 && part.startsWith("0"))
    )
  ) fail(`${field} URL hostname uses a non-canonical numeric spelling`);
}

function publicUrl(value: unknown, field: string, allowlist: ReadonlySet<string>): string {
  const url = stringValue(value, field, 2048);
  if (url !== url.trim() || /[\u0000-\u001f]/.test(url)) {
    fail(`${field} URL contains whitespace or control characters`);
  }
  const decoded = decodeRepeated(url, field);
  if (decoded !== url || decoded.includes("\\") || /(?:^|\/)\.{1,2}(?:\/|$)/.test(decoded)) {
    fail(`${field} URL is not canonically encoded`);
  }
  if (url.includes("?") || url.includes("#")) {
    fail(`${field} URL cannot contain query or fragment secrets`);
  }
  if (url.startsWith("/")) {
    if (url.startsWith("//")) fail(`${field} URL cannot be UNC`);
    return validatePath(url, field, true);
  }
  rejectNonCanonicalNumericAuthority(url, field);

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    fail(`${field} URL must be relative /artifacts or HTTPS`);
  }
  if (parsed.protocol !== "https:") fail(`${field} URL must use HTTPS`);
  if (parsed.username || parsed.password) fail(`${field} URL cannot contain credentials`);
  if (parsed.port && parsed.port !== "443") fail(`${field} URL must use the default HTTPS port`);
  const host = canonicalHost(parsed.hostname, field);
  if (!allowlist.has(host)) fail(`${field} URL hostname is not explicitly allowlisted`);
  if (privateHost(host)) fail(`${field} URL hostname cannot be loopback or private`);
  if (
    !host.includes(":")
    && !/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)
    && (!DNS_HOST.test(host) || !host.includes("."))
  ) fail(`${field} URL hostname is malformed or not public`);
  const path = validatePath(parsed.pathname, field, false);
  const authority = host.includes(":") ? `[${host}]` : host;
  return `https://${authority}${path}`;
}

function sortedUniqueIdentifiers(value: unknown, field: string): string[] {
  const items = arrayValue(value, field).map((item) => identifierValue(item, `${field}[]`));
  if (new Set(items).size !== items.length) fail(`${field} must contain unique values`);
  const sorted = [...items].sort(compareText);
  if (items.some((item, index) => item !== sorted[index])) {
    fail(`${field} must use Python's canonical ordering`);
  }
  return items;
}

function parseReferenceCards(
  value: unknown,
  allowlist: ReadonlySet<string>,
): H3ReferenceCard[] {
  const rawCards = arrayValue(value, "referenceCards");
  if (rawCards.length === 0 || rawCards.length % 3 !== 0) {
    fail("referenceCards must contain complete three-view groups");
  }
  const cards = rawCards.map((rawCard, index): H3ReferenceCard => {
    const field = `referenceCards[${index}]`;
    const card = objectValue(rawCard, field);
    exactKeys(card, [
      "referenceSetId",
      "referenceSetRevisionId",
      "characterId",
      "ageStage",
      "viewName",
      "attemptOrdinal",
      "imageUrl",
      "qcPassed",
      "modelFamily",
      "modelId",
      "revision",
    ], field);
    const viewName = stringValue(card.viewName, `${field}.viewName`) as ReferenceViewName;
    if (!CANONICAL_VIEWS.includes(viewName)) fail(`${field}.viewName is not canonical`);
    const attemptOrdinal = integerValue(card.attemptOrdinal, `${field}.attemptOrdinal`);
    if (attemptOrdinal !== 0 && attemptOrdinal !== 1) {
      fail(`${field}.attemptOrdinal must be 0 or 1`);
    }
    if (booleanValue(card.qcPassed, `${field}.qcPassed`) !== true) {
      fail(`${field}.qcPassed must be true`);
    }
    return {
      referenceSetId: uuidValue(card.referenceSetId, `${field}.referenceSetId`),
      referenceSetRevisionId: uuidValue(
        card.referenceSetRevisionId,
        `${field}.referenceSetRevisionId`,
      ),
      characterId: identifierValue(card.characterId, `${field}.characterId`),
      ageStage: identifierValue(card.ageStage, `${field}.ageStage`),
      viewName,
      attemptOrdinal,
      imageUrl: publicUrl(card.imageUrl, `${field}.imageUrl`, allowlist),
      qcPassed: true,
      modelFamily: literal(card.modelFamily, FLUX_MODEL_FAMILY, `${field}.modelFamily`),
      modelId: literal(card.modelId, FLUX_MODEL_ID, `${field}.modelId`),
      revision: literal(card.revision, FLUX_MODEL_ID, `${field}.revision`),
    };
  });

  let previousGroup = "";
  for (let index = 0; index < cards.length; index += 3) {
    const group = cards.slice(index, index + 3);
    const first = group[0];
    if (
      group.some((card) => (
        card.referenceSetId !== first.referenceSetId
        || card.referenceSetRevisionId !== first.referenceSetRevisionId
        || card.characterId !== first.characterId
        || card.ageStage !== first.ageStage
      ))
      || group.some((card, viewIndex) => card.viewName !== CANONICAL_VIEWS[viewIndex])
    ) {
      fail("referenceCards must use complete canonical three-view groups");
    }
    const groupKey = `${first.characterId}\u0000${first.ageStage}\u0000${first.referenceSetRevisionId}`;
    if (previousGroup && compareText(previousGroup, groupKey) >= 0) {
      fail("referenceCards groups must use Python's canonical ordering");
    }
    previousGroup = groupKey;
  }
  return cards;
}

function parseQcVector(value: unknown, field: string): H3QcVector {
  const vector = objectValue(value, field);
  exactKeys(vector, [...QC_FIELDS], field);
  const result: Partial<H3QcVector> = {};
  for (const name of QC_FIELDS) {
    const score = numberValue(vector[name], `${field}.${name}`);
    if (score < 0 || score > 1) fail(`${field}.${name} must be between 0 and 1`);
    result[name] = score;
  }
  return result as H3QcVector;
}

function parseAttempts(value: unknown, field: string): H3AttemptProjection[] {
  const rawAttempts = arrayValue(value, field);
  if (rawAttempts.length !== 1 && rawAttempts.length !== 2) {
    fail(`${field} must contain attempt 0 and optional repair 1`);
  }
  const attempts = rawAttempts.map((rawAttempt, index): H3AttemptProjection => {
    const attemptField = `${field}[${index}]`;
    const attempt = objectValue(rawAttempt, attemptField);
    exactKeys(attempt, ["attemptOrdinal", "qcVector", "exceptionCodes"], attemptField);
    const ordinal = integerValue(attempt.attemptOrdinal, `${attemptField}.attemptOrdinal`);
    if (ordinal !== index || (ordinal !== 0 && ordinal !== 1)) {
      fail(`${field} must use Python's canonical 0/1 attempt ordering`);
    }
    return {
      attemptOrdinal: ordinal,
      qcVector: parseQcVector(attempt.qcVector, `${attemptField}.qcVector`),
      exceptionCodes: sortedUniqueIdentifiers(
        attempt.exceptionCodes,
        `${attemptField}.exceptionCodes`,
      ),
    };
  });
  return attempts;
}

function parseSequences(value: unknown): H3SequenceProjection[] {
  const rawSequences = arrayValue(value, "sequences");
  if (rawSequences.length === 0) fail("sequences must not be empty");
  const sequenceIds = new Set<string>();
  return rawSequences.map((rawSequence, index): H3SequenceProjection => {
    const field = `sequences[${index}]`;
    const sequence = objectValue(rawSequence, field);
    exactKeys(sequence, [
      "sequenceId",
      "ordinal",
      "durationSeconds",
      "status",
      "attempts",
      "selectedAttemptOrdinal",
      "selectedCleanly",
      "selectedWithQcException",
      "exceptionCodes",
      "selectionReason",
    ], field);
    const ordinal = integerValue(sequence.ordinal, `${field}.ordinal`);
    if (ordinal !== index + 1) fail("sequences must use contiguous Python ordering");
    const duration = numberValue(sequence.durationSeconds, `${field}.durationSeconds`);
    if (duration <= 0) fail(`${field}.durationSeconds must be positive`);
    const attempts = parseAttempts(sequence.attempts, `${field}.attempts`);
    const selectedOrdinal = integerValue(
      sequence.selectedAttemptOrdinal,
      `${field}.selectedAttemptOrdinal`,
    );
    const selected = attempts.find((attempt) => attempt.attemptOrdinal === selectedOrdinal);
    if (selected === undefined) fail(`${field}.selectedAttemptOrdinal is absent from attempts`);
    const clean = selected.exceptionCodes.length === 0;
    if (booleanValue(sequence.selectedCleanly, `${field}.selectedCleanly`) !== clean) {
      fail(`${field}.selectedCleanly disagrees with the selected DTO attempt`);
    }
    if (
      booleanValue(
        sequence.selectedWithQcException,
        `${field}.selectedWithQcException`,
      ) !== !clean
    ) {
      fail(`${field}.selectedWithQcException disagrees with the selected DTO attempt`);
    }
    const exceptionCodes = sortedUniqueIdentifiers(
      sequence.exceptionCodes,
      `${field}.exceptionCodes`,
    );
    if (
      exceptionCodes.length !== selected.exceptionCodes.length
      || exceptionCodes.some((code, codeIndex) => code !== selected.exceptionCodes[codeIndex])
    ) {
      fail(`${field}.exceptionCodes disagrees with the selected DTO attempt`);
    }
    const sequenceId = uuidValue(sequence.sequenceId, `${field}.sequenceId`);
    if (sequenceIds.has(sequenceId)) fail("sequences must use unique sequenceId values");
    sequenceIds.add(sequenceId);
    return {
      sequenceId,
      ordinal,
      durationSeconds: duration,
      status: literal(sequence.status, "delivered", `${field}.status`),
      attempts,
      selectedAttemptOrdinal: selectedOrdinal as 0 | 1,
      selectedCleanly: clean,
      selectedWithQcException: !clean,
      exceptionCodes,
      selectionReason: publicText(sequence.selectionReason, `${field}.selectionReason`),
    };
  });
}

export function parseH3ProductProjection(
  value: unknown,
  options: H3ProjectionParseOptions = {},
): H3ProductProjection {
  const projection = objectValue(value, "projection");
  exactKeys(projection, [
    "schemaVersion",
    "episodeRevisionId",
    "projectId",
    "status",
    "durationSeconds",
    "referenceCards",
    "sequences",
    "playbackUrl",
    "downloadUrl",
    "disclosure",
  ], "projection");
  const allowlist = normalizedAllowlist(options.httpsHostAllowlist ?? []);
  const sequences = parseSequences(projection.sequences);
  const duration = numberValue(projection.durationSeconds, "projection.durationSeconds");
  const sequenceDuration = sequences.reduce(
    (total, sequence) => total + sequence.durationSeconds,
    0,
  );
  if (Math.abs(duration - sequenceDuration) > 1e-9) {
    fail("projection.durationSeconds must equal the sequence duration sum");
  }

  const disclosure = objectValue(projection.disclosure, "projection.disclosure");
  exactKeys(disclosure, ["code", "contentMode", "label", "notice"], "projection.disclosure");
  const contentMode = stringValue(
    disclosure.contentMode,
    "projection.disclosure.contentMode",
    32,
  );
  const label = publicText(disclosure.label, "projection.disclosure.label");
  const notice = publicText(disclosure.notice, "projection.disclosure.notice");
  let publicDisclosure: H3Disclosure;
  if (contentMode === "ai_completed") {
    const combined = `${label}${notice}`;
    if (!combined.toLocaleLowerCase().includes("ai")
      || !combined.includes("补全")
      || !combined.includes("非原文")) {
      fail("AI-completed disclosure must identify AI 补全 and 非原文 content");
    }
    publicDisclosure = {
      code: literal(
        disclosure.code,
        "AI_COMPLETED_NON_ORIGINAL",
        "projection.disclosure.code",
      ),
      contentMode,
      label,
      notice,
    };
  } else if (contentMode === "source_grounded") {
    publicDisclosure = {
      code: literal(
        disclosure.code,
        "SOURCE_GROUNDED",
        "projection.disclosure.code",
      ),
      contentMode,
      label,
      notice,
    };
  } else {
    fail("projection.disclosure.contentMode must be source_grounded or ai_completed");
  }
  return {
    schemaVersion: literal(
      projection.schemaVersion,
      PROJECTION_SCHEMA,
      "projection.schemaVersion",
    ),
    episodeRevisionId: uuidValue(
      projection.episodeRevisionId,
      "projection.episodeRevisionId",
    ),
    projectId: uuidValue(projection.projectId, "projection.projectId"),
    status: literal(projection.status, "succeeded", "projection.status"),
    durationSeconds: duration,
    referenceCards: parseReferenceCards(projection.referenceCards, allowlist),
    sequences,
    playbackUrl: publicUrl(projection.playbackUrl, "projection.playbackUrl", allowlist),
    downloadUrl: publicUrl(projection.downloadUrl, "projection.downloadUrl", allowlist),
    disclosure: publicDisclosure,
  };
}
