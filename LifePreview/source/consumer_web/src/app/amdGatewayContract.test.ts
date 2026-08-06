import { describe, expect, it } from "vitest";

import { amdPreviewGateway } from "../../gateway.config";

describe("AMD preview gateway contract", () => {
  it("serves the private web entrypoint on the cloud loopback port", () => {
    expect(amdPreviewGateway.host).toBe("127.0.0.1");
    expect(amdPreviewGateway.port).toBe(14289);
    expect(amdPreviewGateway.strictPort).toBe(true);
  });

  it.each(["/api", "/artifacts"])("proxies %s to the AMD API loopback port", (path) => {
    expect(amdPreviewGateway.proxy[path as keyof typeof amdPreviewGateway.proxy]).toEqual({
      target: "http://127.0.0.1:18082",
      changeOrigin: false,
    });
  });
});
