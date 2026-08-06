/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./frontend/**/*.{js,ts,jsx,tsx}",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        cyber: {
          base: '#0D0F12',
          card: '#16191E',
          elevated: '#1F242C',
          border: '#2E3541',
          cyan: '#00D2FF',
          amber: '#FFB000',
          emerald: '#00E676',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'cyber-cyan': '0 0 20px rgba(0, 210, 255, 0.25)',
        'cyber-cyan-lg': '0 0 35px rgba(0, 210, 255, 0.35)',
        'cyber-emerald': '0 0 15px rgba(0, 230, 118, 0.3)',
        'cyber-amber': '0 0 15px rgba(255, 176, 0, 0.3)',
      },
    },
  },
  plugins: [],
};
