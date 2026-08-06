/**
 * 应用调色板
 * 支持亮色和暗色两套主题
 */

export interface AppPalette {
  // 基础背景
  surface: string
  surfaceElevated: string
  surfaceMuted: string
  surfacePressed: string
  surfaceActiveHover: string
  surfaceHover: string

  // 操作控件
  controlSurface: string
  controlSurfaceHover: string
  controlSurfacePressed: string
  controlDisabledSurface: string
  controlDisabledBorder: string
  controlDisabledText: string

  // 玻璃效果（液态玻璃感）
  glassBackground: string
  glassBackgroundLight: string
  glassBorder: string
  glassBorderLight: string

  // 边框和分隔
  border: string
  borderHover: string
  borderFocus: string
  divider: string

  // 文本
  text: string
  textStrong: string
  textSecondary: string
  textMuted: string
  textPlaceholder: string
  textDisabled: string
  textInverse: string

  // 主色
  primary: string
  primaryHover: string
  primaryPressed: string
  primarySuppl: string

  // 语义色
  success: string
  successHover: string
  successPressed: string

  info: string
  infoHover: string
  infoPressed: string

  warning: string
  warningHover: string
  warningPressed: string

  error: string
  errorHover: string
  errorPressed: string

  // 特殊用途
  focusShadow: string
  transparent: string
  overlay: string

  // 阴影
  shadowSm: string
  shadowMd: string
  shadowLg: string

  // 代码/终端
  codeBackground: string
  codeBorder: string
}

export const lightPalette: AppPalette = {
  // 基础背景（纯净白）
  surface: '#ffffff',
  surfaceElevated: '#ffffff',
  surfaceMuted: '#fafafa',
  surfacePressed: '#f5f5f5',
  surfaceActiveHover: '#e5e5e5',
  surfaceHover: '#fafafa',

  // 操作控件（保持白底和轻边框，避免禁用态形成灰色块）
  controlSurface: '#ffffff',
  controlSurfaceHover: '#f7f7f8',
  controlSurfacePressed: '#efeff1',
  controlDisabledSurface: '#ffffff',
  controlDisabledBorder: 'rgba(0, 0, 0, 0.07)',
  controlDisabledText: '#8f8f96',

  // 玻璃效果
  glassBackground: 'rgba(255, 255, 255, 0.72)',
  glassBackgroundLight: 'rgba(255, 255, 255, 0.88)',
  glassBorder: 'rgba(0, 0, 0, 0.04)',
  glassBorderLight: 'rgba(0, 0, 0, 0.06)',

  // 边框和分隔（极淡）
  border: 'rgba(0, 0, 0, 0.06)',
  borderHover: 'rgba(0, 0, 0, 0.12)',
  borderFocus: 'rgba(0, 0, 0, 0.8)',
  divider: 'rgba(0, 0, 0, 0.04)',

  // 文本（黑白灰）
  text: '#171717',
  textStrong: '#000000',
  textSecondary: '#737373',
  textMuted: '#a3a3a3',
  textPlaceholder: '#d4d4d4',
  textDisabled: '#e5e5e5',
  textInverse: '#ffffff',

  // 主色（纯黑）
  primary: '#000000',
  primaryHover: '#262626',
  primaryPressed: '#000000',
  primarySuppl: '#404040',

  // 语义色（黑白为主）
  success: '#000000',
  successHover: '#262626',
  successPressed: '#000000',

  info: '#000000',
  infoHover: '#262626',
  infoPressed: '#000000',

  warning: '#737373',
  warningHover: '#525252',
  warningPressed: '#404040',

  error: '#000000',
  errorHover: '#262626',
  errorPressed: '#000000',

  // 特殊用途
  focusShadow: 'rgba(0, 0, 0, 0.1)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.3)',

  // 阴影（柔和）
  shadowSm: '0 2px 8px rgba(0, 0, 0, 0.04)',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.12), 0 4px 8px rgba(0, 0, 0, 0.06)',

  // 代码/终端
  codeBackground: '#fafafa',
  codeBorder: 'rgba(0, 0, 0, 0.06)',
}

export const darkPalette: AppPalette = {
  // 基础背景（纯黑）
  surface: '#000000',
  surfaceElevated: '#0a0a0a',
  surfaceMuted: '#171717',
  surfacePressed: '#262626',
  surfaceActiveHover: '#404040',
  surfaceHover: '#0a0a0a',

  // 操作控件（暗色主题使用干净的分层底色，不用大块中灰）
  controlSurface: '#0a0a0a',
  controlSurfaceHover: '#141416',
  controlSurfacePressed: '#1c1c1f',
  controlDisabledSurface: '#0a0a0a',
  controlDisabledBorder: 'rgba(255, 255, 255, 0.09)',
  controlDisabledText: '#73737a',

  // 玻璃效果
  glassBackground: 'rgba(10, 10, 10, 0.78)',
  glassBackgroundLight: 'rgba(23, 23, 23, 0.88)',
  glassBorder: 'rgba(255, 255, 255, 0.1)',
  glassBorderLight: 'rgba(255, 255, 255, 0.15)',

  // 边框和分隔
  border: 'rgba(255, 255, 255, 0.08)',
  borderHover: 'rgba(255, 255, 255, 0.15)',
  borderFocus: 'rgba(255, 255, 255, 0.8)',
  divider: 'rgba(255, 255, 255, 0.06)',

  // 文本（黑白灰）
  text: '#fafafa',
  textStrong: '#ffffff',
  textSecondary: '#a3a3a3',
  textMuted: '#737373',
  textPlaceholder: '#525252',
  textDisabled: '#404040',
  textInverse: '#000000',

  // 主色（纯白）
  primary: '#ffffff',
  primaryHover: '#fafafa',
  primaryPressed: '#e5e5e5',
  primarySuppl: '#d4d4d4',

  // 语义色（黑白为主）
  success: '#ffffff',
  successHover: '#fafafa',
  successPressed: '#e5e5e5',

  info: '#ffffff',
  infoHover: '#fafafa',
  infoPressed: '#e5e5e5',

  warning: '#a3a3a3',
  warningHover: '#d4d4d4',
  warningPressed: '#737373',

  error: '#ffffff',
  errorHover: '#fafafa',
  errorPressed: '#e5e5e5',

  // 特殊用途
  focusShadow: 'rgba(255, 255, 255, 0.2)',
  transparent: 'transparent',
  overlay: 'rgba(0, 0, 0, 0.6)',

  // 阴影（暗色下更深）
  shadowSm: '0 2px 8px rgba(0, 0, 0, 0.6)',
  shadowMd: '0 4px 16px rgba(0, 0, 0, 0.7), 0 2px 4px rgba(0, 0, 0, 0.5)',
  shadowLg: '0 8px 24px rgba(0, 0, 0, 0.8), 0 4px 8px rgba(0, 0, 0, 0.6)',

  // 代码/终端
  codeBackground: '#0a0a0a',
  codeBorder: 'rgba(255, 255, 255, 0.08)',
}

/**
 * 根据主题模式获取调色板
 */
export function getPalette(isDark: boolean): AppPalette {
  return isDark ? darkPalette : lightPalette
}
