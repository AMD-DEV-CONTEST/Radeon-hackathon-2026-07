# Frontend Integration Guide

> **过期文档 —— 请以 [`frontend-api-handoff.md`](./frontend-api-handoff.md) 为准。**
>
> 这份文件写于 2026-07-30 之前，早于分页、`cutout`、使用证据、参考图条件化、
> 能力矩阵和统一的错误语义。里面的字段形状和状态码有一部分已经不对了。
>
> 本文件保留的唯一价值是那段 TypeScript 客户端骨架。**接口契约不要读这里。**
>
> 另外注意两处曾经写错的地方：
> - 基址**不写进仓库**。这里原先硬编码了一个 Quick Tunnel 地址，那个子域早就失效了；
>   Quick Tunnel 每次重启都会换地址。取当前地址的方式见 handoff 文档开头。
> - 环境变量名以前端实际使用的构建工具为准（Vite 项目是 `VITE_API_BASE_URL`）。

## Development Base URL

```env
# 不要把隧道地址提交进仓库：当前部署 POSTER_API_TOKEN 为空（无鉴权），
# 提交地址等于公开一个谁都能打的后端。地址由后端负责人单独转发。
VITE_API_BASE_URL=<当前隧道地址>
```

Quick Tunnel 地址是临时的，进程重启就变，不要当成生产常量。
API Client
Example TypeScript client:
const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8080";

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(${API_BASE_URL}${path}, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message =
      data && typeof data.error === "string"
        ? data.error
        : Request failed with HTTP ${response.status};
throw new Error(message);
  }
  return data as T;
}

## State-Driven UI

Do not maintain a separate frontend workflow state machine when the backend already returns one.

Use:

```text
status
availableActions
missingFields
plans
poster
reviewSummary
Recommended Screen States
Chat
Show when:
No confirmed plan exists
and the session is not terminal
Render:
Message history
Current brief
Missing fields
Message input
Plan Selection
Show when plans exist and confirmation is available.
Each plan should display:
Name
Concept
Palette
Composition
Composer template
Candidate Generation
Show when:
status == generating_candidates
Poll the Session every two or three seconds.
Display:
poster.progress.completed
poster.progress.total
Candidate Selection
Show when:
availableActions includes select_candidate
Use each candidate's relative imageUrl.
Final Review
Show when:
availableActions includes finalize
Finalization can take several minutes.
Use a long request timeout or an asynchronous UI state.
Download
Show when:
availableActions includes download_final
Use:
poster.resultUrl
poster.thumbnailUrl
Relative Image URLs
Backend image URLs are relative.
Convert:
/api/posters/poster_x/result
to:
const fullImageUrl = `${API_BASE_URL}${relativeImageUrl}`;
Authenticated Images
When POSTER_API_TOKEN is enabled, normal <img src> tags cannot attach a custom header.
Use one of these approaches:
Keep read-only image routes publicly accessible.
Fetch the image as a Blob with an Authorization header.
Introduce short-lived signed image URLs.
Blob example:
export async function fetchProtectedImage(path: string, token: string) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    throw new Error(`Image request failed: ${response.status}`);
  }

  return URL.createObjectURL(await response.blob());
}
Polling
Cloudflare Quick Tunnel does not support SSE.
Use polling during development.
Recommended behavior:
Interval: 2 to 3 seconds
Stop on terminal state
Stop when expected availableAction appears
Back off after network failures
Cancel polling when component unmounts
Example:
const TERMINAL = new Set([
  "succeeded",
  "completed_with_warnings",
  "failed",
  "canceled",
  "needs_user_input",
]);

async function waitForCandidateSelection(sessionId: string) {
  for (;;) {
    const session = await apiRequest<any>(
      /api/ai/sessions/${sessionId},
    );
if (
  session.availableActions?.includes("select_candidate") ||
  TERMINAL.has(session.status)
) {
  return session;
}

await new Promise((resolve) => setTimeout(resolve, 2500));
  }
}

## Timeouts

Recommended client timeouts:

| Operation | Timeout |
|---|---:|
| Create session | 30 seconds |
| Send chat message | 5 minutes |
| Confirm plan | 2 minutes |
| Session poll | 20 seconds |
| Candidate selection | 2 minutes |
| Finalize | 12 minutes |
| Download image | 2 minutes |

## Error Handling

Map status codes as follows:

| HTTP | Meaning |
|---:|---|
| 400 | Invalid JSON or request |
| 404 | Session, poster, candidate, or plan not found |
| 409 | Invalid workflow state |
| 503 | AI service not configured or unavailable |
| 502 | Upstream ComfyUI or VLM failure |
| 500 | Internal storage or repository failure |

## Important Routing Rule

Normal UI flow must select a candidate through:

```text
/api/ai/sessions/{sessionId}/candidates/{candidateId}/select
Do not use:
/api/posters/{posterId}/select
from the normal UI.
Finalize Retry
Finalize is safe to retry.
A network timeout does not necessarily mean that finalization failed.
After a timeout:
GET the Session.
Inspect reviewSummary.
Retry Finalize only if availableActions still includes finalize.
Public Tunnel Caveat
The current Quick Tunnel URL changes when the tunnel restarts.
The frontend should load it from environment configuration instead of source code.
