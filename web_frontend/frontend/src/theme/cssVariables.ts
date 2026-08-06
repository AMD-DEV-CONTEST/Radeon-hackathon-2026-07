/**
 * 将调色板和设计 Token 转换为 CSS 变量注入到 :root
 * 支持运行时切换主题
 */

import type { AppPalette } from './palette'
import { designTokens, tokensToCssVars } from './tokens'

const CSS_VAR_STYLE_ID = 'app-palette-vars'

/**
 * 将 palette 对象转为 CSS 变量字符串
 */
function paletteToCssVars(palette: AppPalette): string {
  const vars: string[] = []
  for (const [key, value] of Object.entries(palette)) {
    // camelCase → kebab-case
    const varName = key.replace(/([A-Z])/g, '-$1').toLowerCase()
    vars.push(`  --app-${varName}: ${value};`)
  }
  return vars.join('\n')
}

/**
 * 将调色板 + 设计 tokens 注入为全局 CSS 变量
 * 在 :root 上定义，所有组件都可用
 */
export function applyPaletteToRoot(palette: AppPalette): void {
  if (typeof document === 'undefined') return

  let styleEl = document.getElementById(CSS_VAR_STYLE_ID) as HTMLStyleElement | null
  if (!styleEl) {
    styleEl = document.createElement('style')
    styleEl.id = CSS_VAR_STYLE_ID
    document.head.appendChild(styleEl)
  }

  styleEl.textContent = `:root {\n${paletteToCssVars(palette)}\n${tokensToCssVars(designTokens)}\n}`
}
