// i18n-boot 单测 —— L02。验证静态壳初始化入口按 data-i18n* 属性正确套用字典，
// 且默认语言是 en。用最小 mock 文档代替真实 DOM——这个仓库没有 jsdom 依赖，
// applyStaticI18n() 本身只用到 querySelectorAll，够用最简单的 mock 覆盖。

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const { applyStaticI18n } = await import(
  pathToFileURL(path.join(here, '..', 'renderer', 'js', 'i18n-boot.js')).href
);
const i18n = await import(
  pathToFileURL(path.join(here, '..', 'renderer', 'js', 'i18n.js')).href
);

function makeEl(attrs = {}) {
  return {
    _attrs: { ...attrs },
    textContent: null,
    title: null,
    placeholder: null,
    getAttribute(name) {
      return this._attrs[name] ?? null;
    },
  };
}

function makeDoc(elements) {
  return {
    documentElement: { lang: '' },
    querySelectorAll(selector) {
      if (selector === '[data-i18n]') return elements.filter((e) => e._attrs['data-i18n']);
      if (selector === '[data-i18n-title]') return elements.filter((e) => e._attrs['data-i18n-title']);
      if (selector === '[data-i18n-placeholder]') return elements.filter((e) => e._attrs['data-i18n-placeholder']);
      return [];
    },
  };
}

test('import 这个模块不会因为没有 document 而崩溃', () => {
  // 已经 import 成功走到这里，说明顶层的 `if (typeof document !== "undefined")`
  // 守卫生效了——Node 测试环境没有全局 document。
  assert.equal(typeof applyStaticI18n, 'function');
});

test('applyStaticI18n 把 data-i18n 元素的 textContent 换成当前语言译文', () => {
  i18n.setLocale('en');
  const el = makeEl({ 'data-i18n': 'project.new' });
  const doc = makeDoc([el]);
  applyStaticI18n(doc);
  assert.equal(el.textContent, 'New Project');
  assert.equal(doc.documentElement.lang, 'en');
});

test('applyStaticI18n 处理 data-i18n-title 和 data-i18n-placeholder', () => {
  i18n.setLocale('en');
  const titleEl = makeEl({ 'data-i18n-title': 'common.selectProcessedAssetHint' });
  const placeholderEl = makeEl({ 'data-i18n-placeholder': 'project.namePlaceholder' });
  const doc = makeDoc([titleEl, placeholderEl]);
  applyStaticI18n(doc);
  assert.equal(titleEl.title, 'Select a processed asset first');
  assert.equal(placeholderEl.placeholder, 'e.g. Hero Walk Animation');
});

test('applyStaticI18n 跟随 setLocale 切到 zh-CN', () => {
  i18n.setLocale('zh-CN');
  const el = makeEl({ 'data-i18n': 'project.new' });
  const doc = makeDoc([el]);
  applyStaticI18n(doc);
  assert.equal(el.textContent, '新建项目');
  assert.equal(doc.documentElement.lang, 'zh-CN');
  i18n.setLocale('en');
});

test('doc 为 null（没有真实 document）时安全跳过，不抛异常', () => {
  assert.doesNotThrow(() => applyStaticI18n(null));
});
