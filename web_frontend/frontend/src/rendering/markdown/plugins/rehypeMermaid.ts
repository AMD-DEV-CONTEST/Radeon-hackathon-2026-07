import { visit } from 'unist-util-visit'

export function rehypeMermaid() {
  return (tree: any) => {
    visit(tree, 'element', (node: any, index: number | undefined, parent: any) => {
      if (!parent || typeof index !== 'number') return
      if (node.tagName !== 'pre') return
      const code = node.children?.[0]
      if (!code || code.tagName !== 'code') return
      const className = Array.isArray(code.properties?.className) ? code.properties.className : []
      if (!className.includes('language-mermaid')) return
      parent.children[index] = {
        type: 'element',
        tagName: 'div',
        properties: { className: ['mermaid'] },
        children: code.children || [],
      }
    })
  }
}
