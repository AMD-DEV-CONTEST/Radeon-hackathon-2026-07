export const CURRENT_FORMAL_ACCOUNT_CHANNEL = "GLOBAL";
export const FORMAL_STORAGE_MODES = Object.freeze([
  "PERSISTENT_PVC",
  "EPHEMERAL"
]);

export const ACCOUNT_PROFILES = Object.freeze({
  GLOBAL: Object.freeze({
    account_channel: "GLOBAL",
    profile_url: "https://radeon-global.anruicloud.com/",
    evidence_role: "CURRENT_FORMAL"
  }),
  CHINA_MAINLAND: Object.freeze({
    account_channel: "CHINA_MAINLAND",
    profile_url: "https://developer.amd.com.cn/radeon/profile",
    evidence_role: "HISTORICAL_ONLY"
  })
});

export function resolveAccountProfile({
  accountChannel,
  profileUrl,
  requireCurrent = false
}) {
  const normalizedChannel = accountChannel?.trim();
  const profile = ACCOUNT_PROFILES[normalizedChannel];
  if (!profile) {
    throw new Error(
      `PRIVATEPLATE_ACCOUNT_CHANNEL must be one of: ${Object.keys(ACCOUNT_PROFILES).join(", ")}.`
    );
  }
  if (
    requireCurrent &&
    normalizedChannel !== CURRENT_FORMAL_ACCOUNT_CHANNEL
  ) {
    throw new Error(
      `New formal runs require PRIVATEPLATE_ACCOUNT_CHANNEL=${CURRENT_FORMAL_ACCOUNT_CHANNEL}; ${normalizedChannel} is historical only.`
    );
  }

  const recordedUrl = profileUrl?.trim() || profile.profile_url;
  if (normalizeUrl(recordedUrl) !== normalizeUrl(profile.profile_url)) {
    throw new Error(
      `PRIVATEPLATE_PROFILE_URL does not match the ${normalizedChannel} account profile.`
    );
  }

  return profile;
}

export function isCurrentFormalAccount(session) {
  try {
    resolveAccountProfile({
      accountChannel: session?.account_channel,
      profileUrl: session?.profile_url,
      requireCurrent: true
    });
    return true;
  } catch {
    return false;
  }
}

export function resolveTemplateProfile({ storageMode, modelDirectory }) {
  const normalizedStorage = storageMode?.trim().toUpperCase();
  if (!FORMAL_STORAGE_MODES.includes(normalizedStorage)) {
    throw new Error(
      `PRIVATEPLATE_STORAGE_MODE must be one of: ${FORMAL_STORAGE_MODES.join(", ")}.`
    );
  }

  const normalizedDirectory = modelDirectory?.trim().toLowerCase();
  if (normalizedDirectory !== "none") {
    throw new Error(
      "PRIVATEPLATE_MODEL_DIRECTORY must be none for the PrivatePlate formal template."
    );
  }

  return {
    storage_mode: normalizedStorage,
    model_directory: normalizedDirectory
  };
}

export function isFormalTemplateProfile(session) {
  try {
    resolveTemplateProfile({
      storageMode: session?.storage_mode,
      modelDirectory: session?.model_directory
    });
    return true;
  } catch {
    return false;
  }
}

function normalizeUrl(value) {
  const url = new URL(value);
  url.hash = "";
  url.search = "";
  url.pathname = url.pathname.replace(/\/+$/, "") || "/";
  return url.toString();
}
