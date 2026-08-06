/**
 * Safely parses basic Markdown strings into HTML tags for rendering.
 * Supports headers, bold, italics, blockquotes, code snippets, lists, and linebreaks.
 */
// Syntax highlighting helper for code blocks
const highlightCodeSyntax = (code, lang) => {
  if (!code) return '';
  let escaped = code;

  // 1. Highlight Comments (// or #)
  escaped = escaped.replace(/(\/\/.*|#.*)/g, '<span class="text-slate-500 italic">$1</span>');

  // 2. Highlight Strings
  escaped = escaped.replace(/(["'])(.*?)\1/g, '<span class="text-emerald-400">$1$2$1</span>');

  // 3. Highlight Keywords
  const keywords = /\b(class|interface|extends|implements|public|private|protected|static|final|void|return|if|else|for|while|do|switch|case|default|break|continue|new|this|super|import|package|function|const|let|var|def|elif|lambda|try|except|catch|finally|throw|throws)\b/g;
  escaped = escaped.replace(keywords, '<span class="text-pink-500 font-bold">$1</span>');

  // 4. Highlight Numbers
  escaped = escaped.replace(/\b(\d+)\b/g, '<span class="text-amber-400">$1</span>');

  // 5. Highlight Types / Built-ins
  const types = /\b(String|int|double|float|long|boolean|char|byte|short|Integer|Double|Float|Long|Boolean|Character|List|Map|Set|HashMap|HashSet|ArrayList|self|print|console|log|System|out|println)\b/g;
  escaped = escaped.replace(types, '<span class="text-sky-400">$1</span>');

  return escaped;
};

/**
 * Safely parses basic Markdown strings into HTML tags for rendering.
 * Supports fenced code blocks, headers, bold, italics, blockquotes, code snippets, lists, and linebreaks.
 */
export const parseMarkdown = (text) => {
  if (!text) return '';

  // Escape HTML tags to prevent XSS (allowing only our generated tags)
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // 1. Multi-line Code blocks (```lang ... ```) - parse before replacing newlines
  html = html.replace(/```([a-zA-Z0-9+#-]+)?\n([\s\S]*?)\n```/g, (match, lang, code) => {
    const highlightedCode = highlightCodeSyntax(code, lang);
    return `<pre class="my-3 p-4 rounded-xl bg-slate-950 text-slate-100 font-mono text-xs overflow-x-auto leading-relaxed border border-slate-800"><div class="flex justify-between items-center pb-1.5 mb-2 border-b border-slate-800 text-[10px] text-slate-400 font-bold uppercase select-none"><span>${lang || 'code'}</span></div><code>${highlightedCode}</code></pre>`;
  });

  // Re-enable blockquotes specifically (since we use > for corrections)
  html = html.replace(/^&gt;\s+(.*)$/gm, '<blockquote class="border-l-4 border-primary-500 pl-4 py-1 my-2 bg-gray-50/50 dark:bg-slate-800/40 rounded-r-lg italic text-gray-700 dark:text-slate-300 font-medium">$1</blockquote>');

  // Headers (### to #)
  html = html.replace(/^### (.*)$/gm, '<h4 class="text-sm font-bold mt-3 mb-1 text-gray-900 dark:text-white">$1</h4>');
  html = html.replace(/^## (.*)$/gm, '<h3 class="text-base font-bold mt-4 mb-2 text-gray-900 dark:text-white">$1</h3>');
  html = html.replace(/^# (.*)$/gm, '<h2 class="text-lg font-black mt-5 mb-2 text-gray-900 dark:text-white">$1</h2>');

  // Bold (**text**)
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong class="font-extrabold text-primary-750 dark:text-primary-400">$1</strong>');

  // Italics (*text*)
  html = html.replace(/\*(.*?)\*/g, '<em class="italic">$1</em>');

  // Bullet points
  html = html.replace(/^\s*-\s+(.*)$/gm, '<li class="ml-4 list-disc text-sm my-1 text-gray-700 dark:text-slate-300">$1</li>');

  // Inline Code (`code`)
  html = html.replace(/`(.*?)`/g, '<code class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-slate-800 font-mono text-xs text-rose-500">$1</code>');

  // Line breaks (except inside <pre> blocks)
  // We temporarily replace linebreaks inside <pre> blocks to avoid breaking them,
  // then restore them after converting other newlines.
  html = html.replace(/(<pre[\s\S]*?<\/pre>)/g, (match) => {
    return match.replace(/\n/g, '<!--NL-->');
  });

  html = html.replace(/\n/g, '<br />');

  // Restore newlines in code blocks
  html = html.replace(/<!--NL-->/g, '\n');

  return html;
};
