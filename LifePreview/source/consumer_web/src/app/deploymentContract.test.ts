import { describe, expect, it } from "vitest";

import nginx from "virtual:consumer-nginx";

describe("consumer deployment contract", () => {
  it("keeps API and signed media same-origin under a restrictive CSP", () => {
    expect(nginx).toContain("location /api/");
    expect(nginx).toContain("location /artifacts/");
    expect(nginx).toContain("connect-src 'self'");
    expect(nginx).toContain("media-src 'self'");
    expect(nginx).toMatch(/Content-Security-Policy "default-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'"/);
    expect(nginx).toContain("try_files $uri /index.html");
    expect(nginx).not.toContain("unsafe-eval");
    expect(nginx).not.toMatch(/connect-src[^;]*(?:https?:|wss?:)/);
  });
});
