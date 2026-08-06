import assert from "node:assert/strict";
import test from "node:test";

import {
  ACCOUNT_PROFILES,
  isFormalTemplateProfile,
  isCurrentFormalAccount,
  resolveAccountProfile,
  resolveTemplateProfile
} from "./account-profile.mjs";

test("Global is the only current formal account profile", () => {
  const profile = resolveAccountProfile({
    accountChannel: "GLOBAL",
    profileUrl: "https://radeon-global.anruicloud.com/",
    requireCurrent: true
  });

  assert.equal(profile, ACCOUNT_PROFILES.GLOBAL);
  assert.equal(isCurrentFormalAccount(profile), true);
});

test("China mainland remains readable as historical evidence", () => {
  const historical = resolveAccountProfile({
    accountChannel: "CHINA_MAINLAND",
    profileUrl: "https://developer.amd.com.cn/radeon/profile"
  });

  assert.equal(historical.evidence_role, "HISTORICAL_ONLY");
  assert.throws(
    () =>
      resolveAccountProfile({
        accountChannel: historical.account_channel,
        profileUrl: historical.profile_url,
        requireCurrent: true
      }),
    /historical only/
  );
});

test("account profile rejects missing channels and mismatched URLs", () => {
  assert.throws(
    () => resolveAccountProfile({ accountChannel: "" }),
    /PRIVATEPLATE_ACCOUNT_CHANNEL/
  );
  assert.throws(
    () =>
      resolveAccountProfile({
        accountChannel: "GLOBAL",
        profileUrl: "https://developer.amd.com.cn/radeon/profile"
      }),
    /does not match/
  );
});

test("formal template records storage and forbids bundled model directories", () => {
  assert.deepEqual(
    resolveTemplateProfile({
      storageMode: "persistent_pvc",
      modelDirectory: "none"
    }),
    {
      storage_mode: "PERSISTENT_PVC",
      model_directory: "none"
    }
  );
  assert.equal(
    isFormalTemplateProfile({
      storage_mode: "EPHEMERAL",
      model_directory: "none"
    }),
    true
  );
  assert.throws(
    () =>
      resolveTemplateProfile({
        storageMode: "PERSISTENT_PVC",
        modelDirectory: "devzone"
      }),
    /must be none/
  );
});
