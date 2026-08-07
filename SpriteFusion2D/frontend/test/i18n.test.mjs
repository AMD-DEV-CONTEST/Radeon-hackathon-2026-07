// i18n 深模块单测 —— L01。覆盖默认语言、未知语言回退、缺失键可见、字典键集合一致、
// PUBLIC_KNOWLEDGE.md §7 术语表全部有键、占位符替换、语言切换与回退到 en。
//
// 注意：i18n.js 是模块级单例（currentLocale 是模块内部状态），所以下面测试按顺序
// 执行，第一条必须在任何 setLocale() 调用之前跑，用来验证「默认 en」。

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const i18n = await import(
  pathToFileURL(path.join(here, '..', 'renderer', 'js', 'i18n.js')).href
);
const enDict = (await import(
  pathToFileURL(path.join(here, '..', 'locales', 'en.js')).href
)).default;
const zhDict = (await import(
  pathToFileURL(path.join(here, '..', 'locales', 'zh-CN.js')).href
)).default;

// docs/luna-workpack/PUBLIC_KNOWLEDGE.md §7 推荐术语表，逐行核对。
const PUBLIC_TERMS = [
  ['project.new', 'New Project', '新建项目'],
  ['project.open', 'Open Project', '打开项目'],
  ['asset.import', 'Import Asset', '导入素材'],
  ['asset.addToProject', 'Add to Project', '收入项目'],
  ['classify.source', 'Source Classification', '来源分类'],
  ['recover.grid', 'Grid Recovery', '网格恢复'],
  ['background.remove', 'Remove Background', '抠图'],
  ['outline.title', 'Outline', '描边'],
  ['pixelify.title', 'Pixelize', '像素化'],
  ['generate.candidates', 'Candidates', '候选'],
  ['asset.assets', 'Assets', '资产'],
  ['asset.frameSets', 'Frame Sets', '帧组'],
  ['history.title', 'History', '历史'],
  ['history.undo', 'Undo', '撤销'],
  ['history.redo', 'Redo', '重做'],
  ['export.title', 'Export', '导出'],
  ['status.backendConnected', 'Backend Connected', '后端已连接'],
];

test('模块加载后默认语言是 en，先于任何 setLocale 调用', () => {
  assert.equal(i18n.getLocale(), 'en');
  assert.equal(i18n.DEFAULT_LOCALE, 'en');
});

test('未知语言回退到 en', () => {
  const resolved = i18n.setLocale('fr');
  assert.equal(resolved, 'en');
  assert.equal(i18n.getLocale(), 'en');
});

test('setLocale 在受支持语言间正常切换', () => {
  assert.equal(i18n.setLocale('zh-CN'), 'zh-CN');
  assert.equal(i18n.getLocale(), 'zh-CN');
  assert.equal(i18n.setLocale('en'), 'en');
  assert.equal(i18n.getLocale(), 'en');
});

test('PUBLIC_KNOWLEDGE 术语表里的每个键在 en 下都有对应译文', () => {
  i18n.setLocale('en');
  for (const [key, enText] of PUBLIC_TERMS) {
    assert.equal(i18n.t(key), enText, `key=${key}`);
  }
});

test('PUBLIC_KNOWLEDGE 术语表里的每个键在 zh-CN 下都有对应译文', () => {
  i18n.setLocale('zh-CN');
  for (const [key, , zhText] of PUBLIC_TERMS) {
    assert.equal(i18n.t(key), zhText, `key=${key}`);
  }
  i18n.setLocale('en');
});

test('占位符 {name} 在两种语言下都能正确替换', () => {
  i18n.setLocale('en');
  assert.equal(i18n.t('common.itemCount', { count: 5 }), '5 items');
  i18n.setLocale('zh-CN');
  assert.equal(i18n.t('common.itemCount', { count: 5 }), '5 项');
  i18n.setLocale('en');
});

test('缺失键返回可见标记，不是 undefined/空字符串，也不含 HTML 标签字符', () => {
  const out = i18n.t('this.key.does.not.exist');
  assert.equal(typeof out, 'string');
  assert.ok(out.length > 0);
  assert.match(out, /this\.key\.does\.not\.exist/);
  assert.equal(out.includes('<'), false);
  assert.equal(out.includes('>'), false);
});

test('当前语言缺键时回退英文（模拟 zh-CN 字典临时缺一个键）', () => {
  const original = zhDict['history.undo'];
  delete zhDict['history.undo'];
  try {
    i18n.setLocale('zh-CN');
    assert.equal(i18n.t('history.undo'), 'Undo');
  } finally {
    zhDict['history.undo'] = original;
    i18n.setLocale('en');
  }
});

test('en.js 与 zh-CN.js 键集合完全一致', () => {
  const enKeys = Object.keys(enDict).sort();
  const zhKeys = Object.keys(zhDict).sort();
  assert.deepEqual(zhKeys, enKeys);
});

test('两份字典都覆盖了 PUBLIC_KNOWLEDGE 术语表的全部键', () => {
  const enKeys = new Set(Object.keys(enDict));
  const zhKeys = new Set(Object.keys(zhDict));
  for (const [key] of PUBLIC_TERMS) {
    assert.ok(enKeys.has(key), `en 缺键 ${key}`);
    assert.ok(zhKeys.has(key), `zh-CN 缺键 ${key}`);
  }
});
