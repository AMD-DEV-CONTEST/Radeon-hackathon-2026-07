/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{js,jsx}'],
  safelist: [
    // assistant-ui 常用类
    { pattern: /^(flex|grid|block|inline|hidden|relative|absolute|sticky)/ },
    { pattern: /^(p|m)(x|y|t|b|l|r)?-\d+/ },
    { pattern: /^(w|h|min-w|min-h|max-w|max-h)-\d+/ },
    { pattern: /^(rounded|border|shadow|opacity|z)-\d+/ },
    { pattern: /^(text|bg|border)-(gray|blue|red|green|yellow|purple|white|black|transparent)/ },
    { pattern: /^(text|bg|border)-(slate|zinc|neutral|stone)/ },
    { pattern: /^text-\[/ },
    { pattern: /^bg-\[/ },
    { pattern: /^(items|justify|self|place|content)-(start|end|center|between|around|stretch)/ },
    { pattern: /^(overflow|resize|cursor|select|pointer-events)/ },
    { pattern: /^(hover|focus|active|disabled|group-hover):/ },
    { pattern: /^(transition|duration|ease|delay)/ },
    { pattern: /^(animate|transform|translate|scale|rotate)/ },
    { pattern: /^leading-/ },
    { pattern: /^whitespace-/ },
    { pattern: /^(gap|space)(-x|-y)?-\d+/ },
    { pattern: /^(shrink|grow|flex-)/ },
    { pattern: /^(top|bottom|left|right)-\d+/ },
    { pattern: /^(inset)(-x|-y)?-\d+/ },
  ],
  theme: { extend: {} },
  plugins: [],
};
