# Terminal half of the demo video.
#
#   bash scripts/record-demo.sh
#
# The pack runs for real against the Radeon box while this records, so the
# elapsed time on screen is the actual GPU round trip, not a cut.

Output demo-terminal.mp4

Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 800
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Type "clear" Enter
Sleep 1s
Show

Type "# Dukaan. One product photo in, a shop's worth of creatives out."
Sleep 1500ms
Enter
Sleep 500ms

Type "# What am I about to run on?"
Enter
Sleep 500ms
Type ".venv/bin/dukaan doctor"
Enter
Sleep 12s

Type "# 48 GB of VRAM behind a container capped at 55 GB of RAM."
Sleep 1s
Enter
Type "# The model pair it has to load is 66 GB. That is the whole problem."
Sleep 2s
Enter
Sleep 1s

Type "clear"
Enter
Sleep 500ms

Type "# One photo, one headline, one price. Everything else is derived."
Enter
Sleep 1s

Type ".venv/bin/dukaan pack examples/brass-ewer.png \"
Enter
Type "  --headline 'Handmade brass ewer' \"
Enter
Type "  --subline '1,450 rupees, free delivery in the city' \"
Enter
Type "  --style festive --contact '+91 90000 00000'"
Enter
Sleep 170s

Sleep 4s
Type "# Three formats, three different moments of one generated clip."
Sleep 2s
Enter
Sleep 1s
Type "ls -la out/brass-ewer/*.png out/brass-ewer/*.wav"
Enter
Sleep 6s

Type "# The suite, and none of it needs the GPU."
Enter
Sleep 1s
Type ".venv/bin/python -m pytest tests/ -q 2>&1 | tail -3"
Enter
Sleep 12s
