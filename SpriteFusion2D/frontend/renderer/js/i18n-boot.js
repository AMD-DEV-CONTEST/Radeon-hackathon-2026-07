// 静态外壳的初始化入口 —— L02。
//
// 唯一职责：把 index.html 里带 data-i18n* 属性的元素替换成当前语言的文案，并让
// <html lang> 跟随 i18n.getLocale()。不涉及任何业务逻辑、不碰 app.js 的状态——
// app.js（L03）后续对同一批元素做的动态更新（项目名、后端状态等）各自独立调用
// t()，不依赖这个文件跑没跑过。
//
// 支持的属性：
//   data-i18n="key"              -> el.textContent = t(key)
//   data-i18n-title="key"        -> el.title = t(key)
//   data-i18n-placeholder="key"  -> el.placeholder = t(key)
//
// 在 Node（单测）环境下 import 这个模块不会做任何事——顶层只在存在真实 `document`
// 时才会自动执行一次，测试可以直接调用 applyStaticI18n(fakeDoc) 传入最小 mock。

import { t, getLocale } from './i18n.js';

export function applyStaticI18n(doc = typeof document !== 'undefined' ? document : null) {
  if (!doc) return;

  doc.documentElement.lang = getLocale();

  for (const el of doc.querySelectorAll('[data-i18n]')) {
    el.textContent = t(el.getAttribute('data-i18n'));
  }
  for (const el of doc.querySelectorAll('[data-i18n-title]')) {
    el.title = t(el.getAttribute('data-i18n-title'));
  }
  for (const el of doc.querySelectorAll('[data-i18n-placeholder]')) {
    el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
  }
}

if (typeof document !== 'undefined') {
  applyStaticI18n();
}
