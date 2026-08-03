# AI Conversation and Requirement Flow

## Goal

The user is not required to provide a complete poster brief in one message.

The backend maintains a persistent AI session that supports continuous conversation until the requirements are sufficiently complete.

## Full Flow

```text
Create Session
        ↓
User sends an initial request
        ↓
Backend stores the user message
        ↓
LLM extracts known event and visual fields
        ↓
Backend returns missingFields
        ↓
User supplies more information
        ↓
Backend merges the new information
        ↓
Repeat until requirements are complete
        ↓
LLM creates multiple design plans
        ↓
Frontend displays plans
        ↓
User confirms one plan
        ↓
Backend generates three candidate images
        ↓
Frontend polls session
        ↓
User selects one candidate
        ↓
Backend composes final poster
        ↓
User finalizes
        ↓
Visual review loop runs
        ↓
Final poster becomes downloadable
Frontend Rule
Do not infer the next action only from status.
Use:
{
  "availableActions": []
}
as the primary UI contract.
Examples:
send_message
confirm_plan
select_candidate
finalize
download_final
Requirement Gathering
The session response includes:
{
  "brief": {},
  "missingFields": [],
  "messages": []
}
The frontend should show:
The accumulated brief
The assistant message
Remaining missing fields
A text input whenever messaging is available
Example Conversation
User message 1
I need a poster for a dark fantasy music festival.
Potential missing information:
[
  "event.title",
  "event.artist",
  "event.date",
  "event.time",
  "event.venue"
]
User message 2
The artist is Maverick. It is on August 21 at 8 PM.
User message 3
The venue is Void Arena. Use black, aged ivory, and deep red.
After the final required fields are collected, the response can include several plans.
Design Plans
Each plan contains information similar to:
{
  "id": "cinematic-wings-embrace",
  "name": "羽翼环抱电影感",
  "concept": "A cinematic centered composition.",
  "palette": [
    "#000000",
    "#C2B280",
    "#A52A2A"
  ],
  "composition": {
    "subject": "center",
    "symmetry": "balanced",
    "titleSafeZone": "top_20_percent",
    "informationSafeZone": "bottom_22_percent"
  },
  "positivePrompt": "...",
  "negativePrompt": "...",
  "composerTemplate": "cinematic_center"
}
Plan Confirmation
After a plan is confirmed:
Session status:
generating_candidates
The backend creates three variants:
Balanced
Dramatic
Graphic
Candidate Polling
The frontend should poll:
GET /api/ai/sessions/{sessionId}
Suggested development polling interval:
2 to 3 seconds
Stop polling when:
availableActions includes select_candidate
or when the session enters a terminal state.
Candidate Selection
Candidate selection must go through the AI Session route:
POST /api/ai/sessions/{sessionId}/candidates/{candidateId}/select
Do not use the low-level Poster selection route from the normal frontend flow.
The Session route keeps Poster and AI Session state synchronized.
Finalization
When:
availableActions includes finalize
the frontend calls:
POST /api/ai/sessions/{sessionId}/finalize
This request may take several minutes because it can run:
VLM review
Automatic recompose
Additional review rounds
Best-version restoration
Final Status
Successful outcomes include:
succeeded
completed_with_warnings
completed_with_warnings does not mean that no poster exists.
It normally means:
The maximum automatic review rounds were reached
The highest-scoring available version was retained
The final image is downloadable
Final Download
When:
availableActions includes download_final
use the Poster response:
{
  "resultUrl": "/api/posters/{posterId}/result",
  "thumbnailUrl": "/api/posters/{posterId}/thumbnail"
}
Prefix relative URLs with the API base URL.
EOF

---

# 5. `docs/api-reference.md`

cat > docs/api-reference.md <<'EOF'
# StagePoster API Reference

## Base URL

Local:

```text
http://127.0.0.1:8080
Development public URL:
https://<当前隧道子域>.trycloudflare.com
The public URL is temporary and must be replaced when the Quick Tunnel restarts.
It is deliberately not committed: POSTER_API_TOKEN is currently empty, so
publishing the address would expose an unauthenticated backend. Read the current
one from backend/run/public-api-url.txt (gitignored) or scripts/status.sh.
Content Type
JSON endpoints use:
Content-Type: application/json
Optional Authentication
The backend supports:
Authorization: Bearer <token>
or:
X-Poster-Token: <token>
When POSTER_API_TOKEN is empty, development requests may be accepted without a token.
Error Response
The current response shape is:
{
  "error": "AI session not found"
}
Frontend code should read error as a user-facing or diagnostic message.
Recommended API Surface
Frontend applications should use AI Session routes as the main workflow.
Create AI Session
POST /api/ai/sessions
Example:
{
  "message": "Create a dark fantasy festival poster with a black throne and enormous wings."
}
Example response fields:
{
  "sessionId": "session_...",
  "status": "...",
  "availableActions": [],
  "brief": {},
  "missingFields": [],
  "messages": [],
  "plans": [],
  "poster": null
}
Get AI Session
GET /api/ai/sessions/{sessionId}
This endpoint also reconciles the AI Session with the current Poster state.
Use it for:
Polling
Page reload recovery
Candidate progress
Finalization state
Download readiness
Send Conversation Message
POST /api/ai/sessions/{sessionId}/messages
Example:
{
  "message": "The event is on August 21 at 8 PM in Void Arena."
}
The response is the updated full AI Session.
Bind Assets
POST /api/ai/sessions/{sessionId}/assets
Use this route for session-associated images or branding assets.
The exact upload or binding payload should follow the current backend asset handler and docs/image-auth.md if asset authentication is enabled.
Confirm Design Plan
POST /api/ai/sessions/{sessionId}/plans/{planId}/confirm
Body:
{}
Expected result:
Session enters generating_candidates.
Select Candidate
POST /api/ai/sessions/{sessionId}/candidates/{candidateId}/select
Body:
{}
Expected result:
Candidate becomes selected
Final poster is composed
Session and Poster become succeeded
resultUrl and thumbnailUrl become available
Finalize Session
POST /api/ai/sessions/{sessionId}/finalize
Body:
{}
Timeout recommendation:
12 minutes
The request can run multiple VLM and composition operations.
Cancel Session
POST /api/ai/sessions/{sessionId}/cancel
Body:
{}
Session Response
A normal session response can contain:
{
  "sessionId": "session_...",
  "status": "succeeded",
  "availableActions": [
    "finalize",
    "download_final"
  ],
  "brief": {
    "event": {},
    "branding": {},
    "visual": {}
  },
  "missingFields": null,
  "selectedPlanId": "cinematic-wings-embrace",
  "posterId": "poster_...",
  "reviewSummary": {
    "finalized": false,
    "accepted": false,
    "rounds": 1,
    "bestRound": 1,
    "bestScore": 88,
    "latestDecision": "RECOMPOSE"
  },
  "messages": [],
  "assets": null,
  "plans": [],
  "poster": {},
  "createdAt": "...",
  "updatedAt": "..."
}
Available Actions
The frontend should render controls based on availableActions.
Typical values:
send_message
confirm_plan
select_candidate
finalize
download_final
Unknown actions should be ignored safely rather than causing a frontend crash.
Poster Read APIs
Get Poster
GET /api/posters/{posterId}
Final Poster Image
GET /api/posters/{posterId}/result
Thumbnail
GET /api/posters/{posterId}/thumbnail
Candidate Image
GET /api/posters/{posterId}/candidates/{candidateId}/image
Create Manual Review
POST /api/posters/{posterId}/review
Body:
{}
This is a low-level review endpoint.
It:
Runs one review
Persists the review
Returns the structured result
It does not execute the complete automatic finalization loop by itself.
List Reviews
GET /api/posters/{posterId}/reviews?limit=20
Poster Timeline
GET /api/posters/{posterId}/timeline
Internal or Diagnostic Routes
The low-level route:
POST /api/posters/{posterId}/select
should not be used by the normal frontend session flow.
Using it directly can temporarily leave the AI Session state stale until the next Session GET reconciliation.
Use:
POST /api/ai/sessions/{sessionId}/candidates/{candidateId}/select
instead.
Candidate Shape
{
  "candidateId": "candidate_...",
  "variantKey": "cinematic-wings-embrace-balanced",
  "variantName": "羽翼环抱电影感 · Balanced",
  "status": "ready",
  "attempt": 1,
  "selected": true,
  "imageUrl": "/api/posters/poster_.../candidates/candidate_.../image"
}
Progress Shape
{
  "completed": 3,
  "total": 3
}
Review Decision Values
ACCEPT
RECOMPOSE
REGENERATE
REWRITE_BRIEF
Finalized with Warnings
Example:
{
  "status": "completed_with_warnings",
  "reviewSummary": {
    "finalized": true,
    "accepted": false,
    "rounds": 2,
    "bestRound": 2,
    "bestScore": 88,
    "latestDecision": "RECOMPOSE",
    "warning": "Maximum review rounds reached or automatic optimization stopped; the best available version was retained."
  }
}
The final image remains valid and downloadable.
CORS
Current development response headers include:
Access-Control-Allow-Origin: *
Access-Control-Allow-Headers: Content-Type, Authorization, X-Poster-Token
Access-Control-Allow-Methods: GET, POST, OPTIONS
