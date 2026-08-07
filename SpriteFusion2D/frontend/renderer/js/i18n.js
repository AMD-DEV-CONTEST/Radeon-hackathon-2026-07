// 最小 i18n 深模块 —— 默认英语，备用 zh-CN（PUBLIC_KNOWLEDGE.md §7）。
//
// 公开接口只有三个：t(key, params)、setLocale(locale)、getLocale()。字典本身
// （frontend/locales/en.js、frontend/locales/zh-CN.js）是纯数据，不在这里内联，
// 方便后续任务（L02–L04）按需扩充键而不用碰这个模块的逻辑。
//
// 约定，供迁移调用方参考：
//   - 键命名 `<域>.<叶子>`，域对应功能分区，叶子小驼峰，详见 locales/en.js 顶部注释。
//   - 占位符语法是 `{name}`，t(key, { name: 'x' }) 做原样字符串替换，不做 HTML 转义
//     也不需要——本模块自始至终只返回字符串，从不触碰 DOM、不调用 innerHTML，调用方
//     必须用 textContent/属性赋值来使用返回值，缺失键的占位标记同样只是普通字符串。
//   - 未知语言（不在字典表里）一律回退默认语言 en，并打印一次 console.warn 方便发现拼写错误。
//   - 当前语言字典缺某个键时，先回退 en 字典；en 也没有则返回可见的
//     `⟦missing:<key>⟧` 标记并 console.warn，保证开发期不会静默吞掉缺失翻译。

import en from '../../locales/en.js';
import zhCN from '../../locales/zh-CN.js';

export const DEFAULT_LOCALE = 'en';
const FALLBACK_LOCALE = 'en';

const DICTS = {
  en,
  'zh-CN': zhCN,
};

let currentLocale = DEFAULT_LOCALE;

function interpolate(template, params) {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name) => (
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
  ));
}

/** 切换当前语言。未收录的语言回退 en，返回值就是实际生效的语言。 */
export function setLocale(locale) {
  if (Object.prototype.hasOwnProperty.call(DICTS, locale)) {
    currentLocale = locale;
  } else {
    console.warn(`[i18n] unknown locale "${locale}", falling back to "${FALLBACK_LOCALE}"`);
    currentLocale = FALLBACK_LOCALE;
  }
  return currentLocale;
}

/** 当前生效的语言代码。 */
export function getLocale() {
  return currentLocale;
}

/**
 * 取一条翻译。params 里的字段会替换模板里的 {字段名}；缺字段时占位符原样保留。
 * 当前语言缺键 -> 回退 en；en 也缺 -> 返回可见标记，绝不返回 undefined 或空字符串，
 * 也绝不拼接/执行 HTML。
 */
export function t(key, params) {
  const dict = DICTS[currentLocale] || DICTS[FALLBACK_LOCALE];
  let template = dict[key];
  if (template === undefined && currentLocale !== FALLBACK_LOCALE) {
    template = DICTS[FALLBACK_LOCALE][key];
  }
  if (template === undefined) {
    console.warn(`[i18n] missing key: ${key}`);
    return `⟦missing:${key}⟧`;
  }
  return interpolate(template, params);
}
