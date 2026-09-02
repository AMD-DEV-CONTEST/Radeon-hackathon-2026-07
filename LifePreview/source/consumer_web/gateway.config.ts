const loopbackHost = "127.0.0.1";

function sameOriginProxy(target: string) {
  return {
    "/api": {
      target,
      changeOrigin: false,
    },
    "/artifacts": {
      target,
      changeOrigin: false,
    },
  };
}

export const developmentGateway = {
  host: loopbackHost,
  port: 4174,
  proxy: sameOriginProxy("http://127.0.0.1:8082"),
};

export const amdPreviewGateway = {
  host: loopbackHost,
  port: 14289,
  strictPort: true,
  proxy: sameOriginProxy("http://127.0.0.1:18082"),
};
