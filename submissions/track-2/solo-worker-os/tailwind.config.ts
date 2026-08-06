import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-outfit)', '-apple-system', 'BlinkMacSystemFont', 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['var(--font-jetbrains-mono)', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        accent: '#f59e0b',
      },
      keyframes: {
        'fade-up': {
          '0%':   { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-down': {
          '0%':   { opacity: '0', transform: 'translateY(-8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%':   { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        'cursor-blink': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.5' },
        },
        'spin-slow': {
          '0%':   { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        'fade-up':      'fade-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both',
        'slide-down':   'slide-down 0.3s cubic-bezier(0.16, 1, 0.3, 1) both',
        'scale-in':     'scale-in 0.2s cubic-bezier(0.16, 1, 0.3, 1) both',
        'cursor-blink': 'cursor-blink 1s step-end infinite',
        'pulse-soft':   'pulse-soft 2s ease-in-out infinite',
        'spin-slow':    'spin-slow 1.5s linear infinite',
      },
      transitionTimingFunction: {
        'expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
};

export default config;
