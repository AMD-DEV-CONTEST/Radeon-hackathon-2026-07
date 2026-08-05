#!/bin/bash
set +e
mkdir -p /workspace && cp -r /src/* /workspace/ 2>/dev/null
chmod -R u+w /workspace 2>/dev/null; rm -f /workspace/executable
cd /workspace && bash compile.sh >/tmp/c 2>&1 && echo BUILD_OK || { echo BUILDFAIL; tail -6 /tmp/c; exit 1; }
R=/tests/eval/test_resources
echo "=== table --pretty (vs table_pretty.golden) ==="
printf '%s' '<table><tr><td>Cell 1</td><td>Cell 2</td></tr><tr><td>Cell 3</td><td>Cell 4</td></tr></table>' | ./executable table --pretty > /tmp/mine 2>/tmp/e
echo "rc=$? | mine bytes=$(wc -c </tmp/mine) golden bytes=$(wc -c <$R/test_output/table_pretty.golden)"
echo "--- MINE ---"; cat -A /tmp/mine | head -14
echo "--- GOLDEN ---"; cat -A "$R/test_output/table_pretty.golden" | head -14
echo "=== universal * < basic.html (vs universal.golden) ==="
./executable '*' < "$R/test_selectors/basic.html" > /tmp/mine2 2>/tmp/e2
echo "rc=$? | mine bytes=$(wc -c </tmp/mine2) golden bytes=$(wc -c <$R/test_selectors/universal.golden)"
diff /tmp/mine2 "$R/test_selectors/universal.golden" | head -12 && echo MATCH || echo "^DIFF above"
