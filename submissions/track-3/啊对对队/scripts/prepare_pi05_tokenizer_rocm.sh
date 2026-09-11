#!/usr/bin/env bash
set -euo pipefail

BASE_SNAPSHOT="${PI05_BASE_SNAPSHOT:-/root/.cache/huggingface/hub/models--lerobot--pi05_base/snapshots/7de663972b7817d2c4cf2d84c821153dfea772e9}"
TOKENIZER_DIR="${PI05_TOKENIZER_DIR:-/root/pi05-assets/paligemma-tokenizer}"
LOCAL_BASE="${PI05_LOCAL_BASE:-/root/pi05-assets/pi05-base-local}"
MODEL_SCOPE_BASE="https://www.modelscope.cn/models/AI-ModelScope/paligemma-3b-pt-224/resolve/master"

declare -A SHA256=(
  [config.json]=e00c72cdff16296bf1229c3267b99f5247d8c740cae84336866338d64fa7918f
  [generation_config.json]=e851cababc44e9fbd81a42b19f9220638832bf8a17e0927bb7cbba97b446893d
  [preprocessor_config.json]=ae5e5f748a642ae71344facf4012b1607852db13f080e42cd12b5db4e75ca7e8
  [special_tokens_map.json]=5ef37093ae4236587b6e8266acb815b46e2db8ce656c66552bfa574d32880405
  [tokenizer.json]=ef6773c135b77b834de1d13c75a4c98ab7a3684ffd602d1831e1f1bf5467c563
  [tokenizer.model]=8986bb4f423f07f8c7f70d0dbe3526fb2316056c17bae71b1ea975e77a168fc6
  [tokenizer_config.json]=3259402b1d1802e02417d7bff75a889ec61d359d15be6050a957b307c48edbbe
)

test -f "${BASE_SNAPSHOT}/model.safetensors" || {
  echo "ERROR: pinned PI0.5 base snapshot is missing: ${BASE_SNAPSHOT}" >&2
  exit 2
}
mkdir -p "${TOKENIZER_DIR}" "${LOCAL_BASE}"
for file in "${!SHA256[@]}"; do
  if [[ ! -f "${TOKENIZER_DIR}/${file}" ]] || ! echo "${SHA256[${file}]}  ${TOKENIZER_DIR}/${file}" | sha256sum -c - >/dev/null 2>&1; then
    curl --fail --location --retry 3 --output "${TOKENIZER_DIR}/${file}.tmp" \
      "${MODEL_SCOPE_BASE}/${file}"
    echo "${SHA256[${file}]}  ${TOKENIZER_DIR}/${file}.tmp" | sha256sum -c -
    mv "${TOKENIZER_DIR}/${file}.tmp" "${TOKENIZER_DIR}/${file}"
  fi
done

for source in "${BASE_SNAPSHOT}"/*; do
  name="$(basename "${source}")"
  [[ "${name}" == policy_preprocessor.json ]] && continue
  ln -sfn "${source}" "${LOCAL_BASE}/${name}"
done
sed \
  "s|\"tokenizer_name\": \"google/paligemma-3b-pt-224\"|\"tokenizer_name\": \"${TOKENIZER_DIR}\"|" \
  "${BASE_SNAPSHOT}/policy_preprocessor.json" \
  > "${LOCAL_BASE}/policy_preprocessor.json"
grep -F "\"tokenizer_name\": \"${TOKENIZER_DIR}\"" "${LOCAL_BASE}/policy_preprocessor.json" >/dev/null

echo "PI05_BASE_MODEL=${LOCAL_BASE}"
