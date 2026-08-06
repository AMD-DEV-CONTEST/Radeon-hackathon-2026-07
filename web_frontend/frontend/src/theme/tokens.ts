/**
 * 设计 Token
 * 与调色板独立，主题切换不影响间距/圆角/字号
 */

export interface DesignTokens {
  // 间距（8px 基础网格）
  spaceXxs: string
  spaceXs: string
  spaceSm: string
  spaceMd: string
  spaceLg: string
  spaceXl: string
  spaceXxl: string

  // 圆角（液态玻璃感 - 更柔和）
  radiusSm: string
  radiusMd: string
  radiusLg: string
  radiusXl: string
  radiusPill: string

  // 字号
  fontXs: string
  fontSm: string
  fontMd: string
  fontLg: string
  fontXl: string
  fontXxl: string

  // 行高
  leadingTight: string
  leadingNormal: string
  leadingRelaxed: string

  // 过渡（更流畅的曲线）
  transitionFast: string
  transitionBase: string
  transitionSlow: string
  transitionSpring: string
  transitionFluid: string

  // 阴影系统（多层软阴影）
  shadowSm: string
  shadowMd: string
  shadowLg: string
  shadowGlass: string

  // 玻璃效果
  glassBlur: string
  glassBlurLight: string
  glassBorder: string

  // 层级
  zBase: string
  zSticky: string
  zDropdown: string
  zDrawer: string
  zModal: string
  zNotification: string

  // 布局
  headerHeight: string
  toolbarHeight: string
  contentMaxWidth: string
  chatMaxWidth: string
}

export const designTokens: DesignTokens = {
  // 间距（苹果风格 - 更大的呼吸感）
  spaceXxs: '4px',
  spaceXs: '8px',
  spaceSm: '12px',
  spaceMd: '16px',
  spaceLg: '24px',
  spaceXl: '32px',
  spaceXxl: '48px',

  // 圆角（苹果风格 - 更大更柔和）
  radiusSm: '10px',
  radiusMd: '14px',
  radiusLg: '24px',
  radiusXl: '32px',
  radiusPill: '999px',

  // 字号
  fontXs: '11px',
  fontSm: '12px',
  fontMd: '13px',
  fontLg: '14px',
  fontXl: '16px',
  fontXxl: '20px',

  // 行高
  leadingTight: '1.25',
  leadingNormal: '1.5',
  leadingRelaxed: '1.65',

  // 过渡（更流畅的曲线 + 弹性）
  transitionFast: '0.18s cubic-bezier(0.34, 1.3, 0.64, 1)',
  transitionBase: '0.35s cubic-bezier(0.34, 1.56, 0.64, 1)',
  transitionSlow: '0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
  transitionSpring: '0.5s cubic-bezier(0.34, 1.8, 0.64, 1)',
  transitionFluid: '0.4s cubic-bezier(0.25, 0.46, 0.45, 0.94)',

  // 多层软阴影系统（苹果风格 - 极柔和）
  shadowSm: '0 2px 8px rgba(0, 0, 0, 0.04)',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06)',
  shadowGlass: '0 12px 48px rgba(0, 0, 0, 0.15), 0 8px 16px rgba(0, 0, 0, 0.08)',

  // 玻璃效果
  glassBlur: 'blur(20px) saturate(180%)',
  glassBlurLight: 'blur(12px) saturate(160%)',
  glassBorder: '1px solid rgba(255, 255, 255, 0.18)',

  // 层级
  zBase: '1',
  zSticky: '10',
  zDropdown: '100',
  zDrawer: '1000',
  zModal: '2000',
  zNotification: '3000',

  // 布局
  headerHeight: '56px',
  toolbarHeight: '40px',
  contentMaxWidth: '1440px',
  chatMaxWidth: '960px',
}

/**
 * 将 tokens 转为 CSS 变量文本片段
 */
export function tokensToCssVars(tokens: DesignTokens): string {
  const vars: string[] = []
  for (const [key, value] of Object.entries(tokens)) {
    const varName = key.replace(/([A-Z])/g, '-$1').toLowerCase()
    vars.push(`  --app-${varName}: ${value};`)
  }
  return vars.join('\n')
}
