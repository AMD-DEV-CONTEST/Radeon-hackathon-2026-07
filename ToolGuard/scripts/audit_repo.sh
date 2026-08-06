#!/bin/bash
echo "############################################"
echo "# 1. Current .gitignore contents"
echo "############################################"
cat .gitignore
echo ""

echo "############################################"
echo "# 2. Files ACTUALLY on GitHub right now"
echo "# (this is exactly what git ls-files shows -"
echo "#  if it's not in this list, it's not pushed)"
echo "############################################"
git ls-files
echo ""

echo "############################################"
echo "# 3. Untracked files (NOT on GitHub)"
echo "# (either correctly ignored, or forgotten)"
echo "############################################"
git status --porcelain | grep '^??' | awk '{print $2}'
echo ""

echo "############################################"
echo "# 4. Scanning COMMITTED files for secrets/keys"
echo "############################################"
SECRET_HITS=$(git ls-files -z | xargs -0 grep -lIE "BEGIN (OPENSSH|RSA) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,}" 2>/dev/null)
if [ -z "$SECRET_HITS" ]; then
  echo "  None found - good."
else
  echo "  !!! WARNING - possible secret found in:"
  echo "$SECRET_HITS"
fi
echo ""

echo "############################################"
echo "# 5. Scanning COMMITTED files for email addresses"
echo "############################################"
EMAIL_HITS=$(git ls-files -z | xargs -0 grep -lIE "[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}" 2>/dev/null)
if [ -z "$EMAIL_HITS" ]; then
  echo "  None found."
else
  echo "  Found email address(es) in:"
  echo "$EMAIL_HITS"
fi
echo ""

echo "############################################"
echo "# 6. Checking no SSH keys are sitting INSIDE the repo folder"
echo "# (they should only exist in ~/.ssh and /persistent/ssh_backup,"
echo "#  both OUTSIDE this repo entirely)"
echo "############################################"
KEY_IN_REPO=$(find . -path ./.git -prune -o -iname "id_ed25519*" -print)
if [ -z "$KEY_IN_REPO" ]; then
  echo "  None found inside repo - good."
else
  echo "  !!! WARNING - key file found inside repo:"
  echo "$KEY_IN_REPO"
fi
echo ""

echo "############################################"
echo "# 7. Full file tree on disk (excluding .git internals)"
echo "############################################"
find . -path ./.git -prune -o -type f -print | sort
