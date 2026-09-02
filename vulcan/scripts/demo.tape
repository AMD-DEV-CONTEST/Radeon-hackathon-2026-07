# VHS tape for the AMD AI DevMaster demo video, Track 2.
#
#   bash scripts/record-demo.sh
#
# Every command below really executes against the Radeon endpoint and the
# output is whatever the machine returns. Nothing is staged or replayed.
#
# The tape is built around what Track 2 actually scores, which is not the same
# as what is impressive to a developer:
#
#   20 pts  core capabilities: task decomposition, tool invocation, RAG, memory
#   20 pts  smooth multi-turn interaction
#   20 pts  core inference running on the Radeon GPU
#   20 pts  targeted optimization for inference speed
#
# So the session has to SHOW several distinct tools being chosen, context
# carried across turns, and memory surviving a restart. An earlier cut of this
# video used one tool twice and demonstrated none of that, which left up to 40
# points unevidenced.
#
# VHS drops frames while the screen is idle, so runtime is driven by streamed
# output rather than by Sleep. Real agent work is what lengthens the video.

Output demo-raw.mp4

Set Shell "bash"
Set FontSize 15
Set Width 1500
Set Height 860
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms

Hide
Type "clear" Enter
Sleep 1s
Show

Type "# Vulcan: a codebase agent whose every token runs on an AMD Radeon GPU."
Sleep 1200ms
Enter
Type "# Nothing goes to a third-party LLM API."
Sleep 1200ms
Enter
Sleep 500ms

Type "bash scripts/show-endpoint.sh"
Enter
Sleep 8s

Type "# gfx1100, 48 GiB, ROCm 7.2.4. Committed, not asserted."
Enter
Sleep 800ms
Type "grep -A6 'python -c' bench-results/radeon-device.txt"
Enter
Sleep 6s

Type "clear"
Enter
Sleep 500ms

Type "# 1. RAG. Index this repository into a local semantic store."
Enter
Sleep 800ms
Type "vulcan index ."
Enter
Sleep 25s

Type "clear"
Enter
Sleep 500ms

Type "# 2. A multi-turn session. Watch which tool it picks for each question."
Enter
Sleep 1s
Type "vulcan chat"
Enter
Sleep 6s

Type "Which file implements the benchmark harness, and what does it measure?"
Enter
Sleep 70s

Type "Now run that file's tests with .venv/bin/python -m pytest -q and tell me how many pass."
Enter
Sleep 80s

Type "Grep for VULCAN_ENABLE_THINKING and explain what setting it to false does."
Enter
Sleep 75s

Type "Use the remember tool to store this: every new benchmark must be committed as JSON under bench-results, never pasted into docs."
Enter
Sleep 55s

Ctrl+D
Sleep 3s

Type "# 3. Memory is on disk, not in the context window. New session, same fact."
Enter
Sleep 1s
Type "vulcan chat"
Enter
Sleep 6s

Type "What did I tell you about where new benchmarks must be committed?"
Enter
Sleep 55s

Ctrl+D
Sleep 3s

Type "clear"
Enter
Sleep 500ms

Type "# 4. The optimization half. Is the stock serving config actually right?"
Enter
Sleep 1s
Type "# Capping the batch at 4 removes continuous batching, and the scaling with it."
Enter
Sleep 1500ms
Type "# The control: stock config against the same model with the batch capped."
Enter
Sleep 2s
Type "vulcan bench-compare bench-results/gmu092-stock-conc.json bench-results/maxseqs4-conc.json"
Enter
Sleep 16s

Type "# 8.12x stock, 4.07x capped. The capped run scales to exactly its own cap."
Sleep 2500ms
Enter
Sleep 4s
