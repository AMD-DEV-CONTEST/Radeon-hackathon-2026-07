/**
 * security.js — Shared XSS prevention utilities.
 * Include in any template that renders user data.
 */
function escHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;")
    .replace(/`/g, "&#x60;");
}
/**
 * Build a DOM element from a tag + attributes + text content.
 * Safer than innerHTML because textContent auto-escapes.
 */
function domEl(tag, attrs, text) {
  var el = document.createElement(tag);
  if (attrs) { for (var k in attrs) el.setAttribute(k, attrs[k]); }
  if (text != null) el.textContent = text;
  return el;
}
