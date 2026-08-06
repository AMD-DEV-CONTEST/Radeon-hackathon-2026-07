#!/usr/bin/env node
import {
  resolveAccountProfile,
  resolveTemplateProfile
} from "./account-profile.mjs";

const profile = resolveAccountProfile({
  accountChannel: process.env.PRIVATEPLATE_ACCOUNT_CHANNEL,
  profileUrl: process.env.PRIVATEPLATE_PROFILE_URL,
  requireCurrent: true
});
const template = resolveTemplateProfile({
  storageMode: process.env.PRIVATEPLATE_STORAGE_MODE,
  modelDirectory: process.env.PRIVATEPLATE_MODEL_DIRECTORY
});

console.log(
  JSON.stringify(
    {
      status: "PASS",
      account_channel: profile.account_channel,
      profile_url: profile.profile_url,
      evidence_role: profile.evidence_role,
      ...template
    },
    null,
    2
  )
);
