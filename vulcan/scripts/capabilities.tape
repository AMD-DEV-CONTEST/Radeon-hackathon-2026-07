# Second segment of the demo video: what changed after the first recording.
#
#   bash scripts/record-capabilities.sh
#
# This one runs against the LOCAL backend, not the Radeon, and the video says
# so on the card before it. The first segment is the Radeon evidence and is
# left untouched; re-recording it would mean destroying the instance currently
# holding another track's work, and the ROCm numbers are committed as JSON
# either way. Running the same agent on a second backend is also the
# backend-agnostic claim being exercised rather than asserted.
#
# Budget is tight: the finished video must stay inside 3 to 5 minutes and the
# first segment is already 3:39, so this has to land near a minute. Every
# command here is chosen because it evidences a scored criterion:
#
#   privacy-check  the whole premise of "private AI agents", made falsifiable
#   follow-up      multi-turn context, which did not exist before
#   rag-bench      retrieval quality, swept rather than claimed

Output capabilities-raw.mp4

Set Shell "bash"
Set FontSize 17
Set Width 1400
Set Height 800
Set Padding 22
Set Theme "Catppuccin Mocha"
Set TypingSpeed 32ms

Hide
Type "cd /Users/himanshujha/n/vulcan" Enter
Type "export VULCAN_BASE_URL=http://localhost:11434/v1 VULCAN_API_KEY=local VULCAN_MODEL=qwen3:4b-instruct VULCAN_EMBED_MODEL=mxbai-embed-large" Enter
Type "clear" Enter
Sleep 1s
Show

Type "# The claim is that no token reaches a third party. Check it."
Enter
Sleep 500ms
Type ".venv/bin/vulcan privacy-check --name planbench"
Enter
Sleep 22s

Type "# A follow-up that only makes sense with context."
Enter
Sleep 500ms
Type ".venv/bin/python scripts/followup.py"
Enter
Sleep 26s

Type "# Retrieval: the weight was swept, not guessed."
Enter
Sleep 500ms
Type ".venv/bin/vulcan rag-bench --name planbench"
Enter
Sleep 14s
