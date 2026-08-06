#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
NC='\033[0m'

echo "Generating Demo Data for Bunker..."

# 1. Create data/documents/ directory structure
mkdir -p ../data/documents/emails
mkdir -p ../data/documents/calendar

# 2. Write sample business documents
cat << 'EOF' > ../data/documents/q3_report.txt
Q3 Financial Report
Total Revenue: $4.5M
Operating Expenses: $2.1M
Net Income: $2.4M
Notes: Excellent growth in enterprise sector.
EOF

cat << 'EOF' > ../data/documents/project_roadmap.md
# Project Roadmap
## Q4 2026
- Release Bunker 1.0
- Integrate ROCm optimizations
## Q1 2027
- Multi-agent deployment
EOF

cat << 'EOF' > ../data/documents/team_meeting_notes.txt
Meeting Notes: AI Team (Oct 15)
- Jane to finalize the vLLM config
- John to test the latest ROCm drivers (6.2)
- Action: Review model quantization impacts.
EOF

cat << 'EOF' > ../data/documents/budget_overview.txt
Budget Overview 2026
- Cloud Compute: $150k
- Hardware (AMD MI300X): $500k
- Software Licenses: $50k
EOF

# 3. Create sample email JSON files
cat << 'EOF' > ../data/documents/emails/email_1.json
{
  "subject": "Re: Bunker Launch",
  "from": "alice@bunker.com",
  "date": "2026-10-10",
  "body": "The launch is on track for next Friday!"
}
EOF

cat << 'EOF' > ../data/documents/emails/email_2.json
{
  "subject": "Hardware Invoice",
  "from": "billing@amd.com",
  "date": "2026-10-12",
  "body": "Attached is the invoice for the MI300X cluster."
}
EOF

cat << 'EOF' > ../data/documents/emails/email_3.json
{
  "subject": "Lunch?",
  "from": "bob@bunker.com",
  "date": "2026-10-13",
  "body": "Are we still doing lunch tomorrow?"
}
EOF

# 4. Create sample calendar events
cat << 'EOF' > ../data/documents/calendar/events.json
[
  {"event": "Daily Standup", "time": "10:00 AM"},
  {"event": "Client Pitch", "time": "1:00 PM"},
  {"event": "Code Review", "time": "3:00 PM"},
  {"event": "Design Sync", "time": "4:30 PM"},
  {"event": "Happy Hour", "time": "5:30 PM"}
]
EOF

# 5. Print summary
echo -e "${GREEN}Demo data generated successfully in data/documents/${NC}"
