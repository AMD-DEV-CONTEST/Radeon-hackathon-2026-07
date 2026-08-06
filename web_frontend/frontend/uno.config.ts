import { defineConfig, presetUno, presetAttributify, presetIcons } from 'unocss'
import { RESOURCE_ICON_CLASSES } from './src/utils/resourcePresentation'

export default defineConfig({
  safelist: RESOURCE_ICON_CLASSES,
  presets: [
    presetUno(),
    presetAttributify(),
    presetIcons({
      scale: 1.2,
      warn: true,
    }),
  ],
  shortcuts: {
    // 布局
    'flex-center': 'flex items-center justify-center',
    'flex-col-center': 'flex flex-col items-center justify-center',
    'flex-between': 'flex items-center justify-between',
    'flex-start': 'flex items-center justify-start',
    'flex-end': 'flex items-center justify-end',
    'absolute-center': 'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2',
    'stack-v': 'flex flex-col',
    'stack-h': 'flex flex-row',

    // 过渡
    'transition-base': 'transition-all duration-200 ease-in-out',
    'transition-fast': 'transition-all duration-100 ease-in-out',
    'transition-slow': 'transition-all duration-300 ease-in-out',

    // 文本
    'text-truncate': 'overflow-hidden whitespace-nowrap [text-overflow:ellipsis]',

    // 尺寸
    'size-full': 'w-full h-full',
    'min-size-0': 'min-w-0 min-h-0',
  },
  theme: {
    colors: {
      primary: {
        DEFAULT: '#18a058',
        hover: '#36ad6a',
        pressed: '#0c7a43',
      },
      info: {
        DEFAULT: '#2080f0',
        hover: '#4098fc',
        pressed: '#1060c9',
      },
      success: {
        DEFAULT: '#18a058',
        hover: '#36ad6a',
        pressed: '#0c7a43',
      },
      warning: {
        DEFAULT: '#f0a020',
        hover: '#fcb040',
        pressed: '#c97c10',
      },
      error: {
        DEFAULT: '#d03050',
        hover: '#de576d',
        pressed: '#ab1f3f',
      },
    },
    breakpoints: {
      sm: '640px',
      md: '768px',
      lg: '1024px',
      xl: '1280px',
      '2xl': '1536px',
    },
  },
})
