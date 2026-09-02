# Image Authentication

## How it works

When `POSTER_API_TOKEN` is enabled, browsers cannot automatically attach
`X-Poster-Token` to `<img src="/api/posters/.../image">` requests.

Choose one of three approaches:

1. **Local dev — disable Backend Token.** Keep `POSTER_API_TOKEN=` empty.
2. **Frontend uses `fetch()` with headers, converts to Blob URL.** The
   frontend fetches via `X-Poster-Token`, then creates a local object URL
   for `<img>`.
3. **Backend generates short-lived signed image URLs.** Recommended for
   production.

For hackathon MVP, option 1 or 2 is sufficient. Implement signed URLs or
Cookie-based auth before going to production.
