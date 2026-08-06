/**
 * Privacy-minimized model context: health tags are never bulk-exposed.
 * A member's healthTags may appear in the model payload only when the user
 * text explicitly mentions that member and a constraint-related cue.
 */

export type PrivacyMember = {
  id: string;
  displayName: string;
  roleLabel: string;
  healthTags?: string[];
  aliases?: string[];
};

/** Generic Chinese cues that a dietary / health constraint is under discussion. */
const CONSTRAINT_CUE =
  /少盐|低盐|控盐|钠|控糖|血糖|血压|高血压|糖尿病|过敏|忌口|健康约束|饮食约束|约束|克制|主食|碳水|guardrail|sodium|salt|diabetes|hypertension/i;

const DEFAULT_ROLE_ALIASES: Record<string, readonly string[]> = {
  admin: ["我", "本人", "管理员"],
  father: ["爸爸", "父亲", "老爸"],
  mother: ["妈妈", "母亲", "老妈"],
  member: []
};

export function memberMentionAliases(member: PrivacyMember): string[] {
  const roleAliases = DEFAULT_ROLE_ALIASES[member.roleLabel] ?? [];
  return [
    ...new Set(
      [member.displayName, ...(member.aliases ?? []), ...roleAliases].filter(
        (value) => value.length > 0
      )
    )
  ];
}

export function isMemberMentioned(
  userText: string,
  member: PrivacyMember
): boolean {
  return memberMentionAliases(member).some((alias) => {
    if (!alias) return false;
    // Single-char "我" must not match plural 我们 or polite 给我….
    if (alias === "我") {
      if (userText.includes("本人") || userText.includes("管理员")) return true;
      if (userText.includes("我们") || userText.includes("给我")) return false;
      return (
        userText.includes("我自己") ||
        /只有我|就我|我一个人/.test(userText) ||
        /(?:^|[，。！？、\s])我(?:[，。！？、\s]|$)/.test(userText)
      );
    }
    return userText.includes(alias);
  });
}

export function hasConstraintCue(userText: string): boolean {
  return CONSTRAINT_CUE.test(userText);
}

/**
 * Build the member list that may be sent to the model.
 * healthTags are omitted unless both the member and a constraint cue appear.
 */
export function buildPrivacyMinimizedMemberDirectory(
  members: PrivacyMember[],
  userText: string
): Array<{
  id: string;
  displayName: string;
  roleLabel: string;
  healthTags?: string[];
}> {
  const constraintDiscussed = hasConstraintCue(userText);
  return members.map((member) => {
    const base = {
      id: member.id,
      displayName: member.displayName,
      roleLabel: member.roleLabel
    };
    if (
      constraintDiscussed &&
      isMemberMentioned(userText, member) &&
      Array.isArray(member.healthTags) &&
      member.healthTags.length > 0
    ) {
      return { ...base, healthTags: [...member.healthTags] };
    }
    return base;
  });
}

/**
 * True when a prepared model member payload still carries health tags that
 * the privacy rule would not allow for this user text.
 */
export function detectPrivacyLeakInMemberPayload(
  modelMembers: Array<{ id: string; healthTags?: string[] }>,
  fullMembers: PrivacyMember[],
  userText: string
): boolean {
  const allowed = new Map(
    buildPrivacyMinimizedMemberDirectory(fullMembers, userText).map(
      (member) => [member.id, member.healthTags ?? []]
    )
  );
  for (const member of modelMembers) {
    const tags = member.healthTags ?? [];
    if (tags.length === 0) continue;
    const permitted = allowed.get(member.id) ?? [];
    if (tags.some((tag) => !permitted.includes(tag))) {
      return true;
    }
  }
  return false;
}

/**
 * Detect sensitive health tags in raw model tool arguments that were not
 * allowed into this turn's model context.
 *
 * This checks the model output itself. It is intentionally separate from
 * detectPrivacyLeakInMemberPayload(), which only validates the request sent
 * to the model.
 */
export function detectPrivacyLeakInToolArguments(
  rawArguments: Record<string, unknown>,
  fullMembers: PrivacyMember[],
  userText: string
): boolean {
  // Model must never own health tag arrays; tags are resolved server-side from memberIds.
  if ("memberTags" in rawArguments && rawArguments.memberTags !== undefined) {
    return true;
  }

  const allowedTags = allowedHealthTags(fullMembers, userText);
  const protectedTags = new Set(
    fullMembers.flatMap((member) => member.healthTags ?? [])
  );
  return collectStrings(rawArguments).some(
    (value) =>
      protectedTags.has(value) &&
      !allowedTags.has(value)
  );
}

export function detectPrivacyLeakInToolArgumentText(
  rawArguments: string,
  fullMembers: PrivacyMember[],
  userText: string
): boolean {
  const allowedTags = allowedHealthTags(fullMembers, userText);
  return fullMembers
    .flatMap((member) => member.healthTags ?? [])
    .some(
      (tag) => !allowedTags.has(tag) && rawArguments.includes(tag)
    );
}

/**
 * memberTags in tool args are a privacy surface: only tags that were allowed
 * into the model context (or would be allowed by the same rule) may appear.
 */
export function filterAllowedMemberTags(
  memberTags: string[],
  fullMembers: PrivacyMember[],
  userText: string
): string[] {
  if (!Array.isArray(memberTags) || memberTags.length === 0) {
    return [];
  }
  const allowedTags = allowedHealthTags(fullMembers, userText);
  return memberTags.filter((tag) => allowedTags.has(tag));
}

function allowedHealthTags(
  fullMembers: PrivacyMember[],
  userText: string
): Set<string> {
  return new Set(
    buildPrivacyMinimizedMemberDirectory(fullMembers, userText).flatMap(
      (member) => member.healthTags ?? []
    )
  );
}

function collectStrings(value: unknown): string[] {
  if (typeof value === "string") {
    return [value];
  }
  if (Array.isArray(value)) {
    return value.flatMap(collectStrings);
  }
  if (value && typeof value === "object") {
    return Object.values(value).flatMap(collectStrings);
  }
  return [];
}
