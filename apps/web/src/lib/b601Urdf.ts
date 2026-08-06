/** B601 URDF URLs — browser-safe LOD tiers (full mesh is 1.3M+ tris). */
/** v=4: joint3 limits symmetric + web B601_DISPLAY_SIGN flips elbow/wrist for DM. */
const B601_URDF_REV = 'v=4'
export const B601_URDF_FULL = `/api/urdf/b601_rs/b601_rs.urdf?${B601_URDF_REV}`
/** Robots 列表卡片 — 轻量 ~80k tris，与 SO-101/Reachy 同屏不炸 GPU */
export const B601_URDF_CATALOG = `/api/urdf/b601_rs/b601_rs_catalog.urdf?${B601_URDF_REV}`
/** 工作台 / 新手上手 Stage — 中高精度 ~450k tris，单 Canvas 下接近实机外观 */
export const B601_URDF_STAGE = `/api/urdf/b601_rs/b601_rs_preview.urdf?${B601_URDF_REV}`
