// 英语字典 —— 默认语言。键必须与 zh-CN.js 完全一致（由 i18n.test.mjs 校验）。
//
// 命名约定：`<域>.<叶子>`，域取自 PUBLIC_KNOWLEDGE.md §7 的功能分区（project/asset/
// classify/recover/background/outline/pixelify/generate/history/export/status/
// common），叶子用小驼峰。新增键时优先复用已有域，不要为单个字符串新开一个域。
//
// 术语来源：docs/luna-workpack/PUBLIC_KNOWLEDGE.md §7 “推荐术语”表，逐行对应。

export default {
  'project.new': 'New Project',
  'project.open': 'Open Project',
  'asset.import': 'Import Asset',
  'asset.addToProject': 'Add to Project',
  'asset.assets': 'Assets',
  'asset.frameSets': 'Frame Sets',
  'classify.source': 'Source Classification',
  'recover.grid': 'Grid Recovery',
  'background.remove': 'Remove Background',
  'outline.title': 'Outline',
  'pixelify.title': 'Pixelize',
  'generate.candidates': 'Candidates',
  'history.title': 'History',
  'history.undo': 'Undo',
  'history.redo': 'Redo',
  'export.title': 'Export',
  'status.backendConnected': 'Backend Connected',
  'common.itemCount': '{count} items',
};
