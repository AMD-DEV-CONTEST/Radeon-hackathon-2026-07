# Manual Test Scripts

This folder contains hand-run validation or data population scripts. They are not part of the automated test suite.

## Scripts

| Script | Notes |
|---|---|
| `v24_chapter_test.py` | Inserts and verifies Chapter 30 sample entities and relations in `novel_world_zh.db`. |
| `v25_chapter_test.py` | Inserts and verifies Chapter 25 sample entities and relations in `novel_world_zh.db`. |

## Warning

These scripts mutate the configured SQLite database. Do not run them during routine test passes or roadmap/documentation work.
