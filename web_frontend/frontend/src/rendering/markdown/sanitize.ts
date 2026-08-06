import { defaultSchema } from 'rehype-sanitize'

export function markdownSanitizeSchema() {
  const schema: any = structuredClone(defaultSchema)
  schema.attributes = {
    ...schema.attributes,
    '*': [
      ...(schema.attributes?.['*'] || []),
      'className',
      'dataLanguage',
      'ariaHidden',
      'ariaLabel',
      'role',
    ],
    a: [
      ...(schema.attributes?.a || []),
      'href',
      'title',
      'target',
      'rel',
    ],
    code: [
      ...(schema.attributes?.code || []),
      'className',
    ],
    div: [
      ...(schema.attributes?.div || []),
      'className',
    ],
    span: [
      ...(schema.attributes?.span || []),
      'className',
      'style',
    ],
  }
  schema.tagNames = Array.from(new Set([
    ...(schema.tagNames || []),
    'div',
    'span',
    'math',
    'semantics',
    'mrow',
    'mi',
    'mn',
    'mo',
    'msup',
    'msub',
    'msubsup',
    'mfrac',
    'msqrt',
    'mroot',
    'mtable',
    'mtr',
    'mtd',
    'annotation',
  ]))
  return schema
}
