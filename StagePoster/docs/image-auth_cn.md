# 图片鉴权

## 工作原理

启用 `POSTER_API_TOKEN` 之后，浏览器无法为
`<img src="/api/posters/.../image">` 这类请求自动附加 `X-Poster-Token`。

三种方案选其一：

1. **本地开发 —— 不启用 Backend Token。** 保持 `POSTER_API_TOKEN=` 为空。
2. **前端用 `fetch()` 带 Header，再转成 Blob URL。** 前端通过
   `X-Poster-Token` 取图，然后创建本地 object URL 供 `<img>` 使用。
3. **后端生成短时签名图片 URL。** 生产环境推荐。

黑客松 MVP 用方案 1 或 2 就够。上生产前再实现签名 URL 或基于 Cookie 的鉴权。
