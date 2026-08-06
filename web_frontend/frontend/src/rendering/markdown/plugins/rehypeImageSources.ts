import { visit } from 'unist-util-visit'
import { isImageResource } from '@/utils/workspaceResources'
import type { MarkdownRenderSurface } from '../types'

type ImageUrlResolver = (source: string) => string | null

interface ElementNode {
  type: 'element'
  tagName: string
  properties?: Record<string, unknown>
  children?: Array<ElementNode | TextNode>
}

interface TextNode {
  type: 'text'
  value: string
}

export function rehypeImageSources() {
  return (tree: any, file: any) => {
    const resolver = file.data?.resolveImageUrl as ImageUrlResolver | undefined
    const surface = file.data?.surface as MarkdownRenderSurface | undefined
    if (!resolver) return

    visit(tree, 'element', (node: any, index: number | undefined, parent: any) => {
      if (node.tagName === 'img') {
        const source = propertyString(node, 'src')
        const resolved = resolver(source)
        if (resolved) {
          node.properties = { ...node.properties, src: resolved }
          return
        }
        replaceNode(parent, index, textNode(propertyString(node, 'alt') || source))
        return
      }

      if (surface !== 'chat_message') return

      if (node.tagName === 'a') {
        const source = propertyString(node, 'href')
        const image = resolvedImage(source, resolver, nodeText(node))
        if (image) {
          node.properties = {
            ...node.properties,
            href: image.properties?.src,
            target: '_blank',
            rel: 'noopener noreferrer',
          }
          node.children = [image]
        }
        return
      }

      if (node.tagName === 'code' && parent?.tagName !== 'pre') {
        const source = standaloneNodeText(node)
        const imageLink = resolvedImageLink(source, resolver)
        if (imageLink) replaceNode(parent, index, imageLink)
        return
      }

      if (node.tagName === 'p' && node.children?.length === 1 && node.children[0]?.type === 'text') {
        const source = standaloneNodeText(node)
        const imageLink = resolvedImageLink(source, resolver)
        if (imageLink) node.children = [imageLink]
      }
    })
  }
}

function resolvedImageLink(source: string, resolver: ImageUrlResolver): ElementNode | null {
  const image = resolvedImage(source, resolver, source)
  if (!image) return null
  return {
    type: 'element',
    tagName: 'a',
    properties: {
      href: image.properties?.src,
      target: '_blank',
      rel: 'noopener noreferrer',
    },
    children: [image],
  }
}

function resolvedImage(source: string, resolver: ImageUrlResolver, alt: string): ElementNode | null {
  if (!source || !isImageResource(source)) return null
  const resolved = resolver(source)
  if (!resolved) return null
  return {
    type: 'element',
    tagName: 'img',
    properties: {
      src: resolved,
      alt: alt || source,
    },
    children: [],
  }
}

function standaloneNodeText(node: ElementNode): string {
  const value = nodeText(node).trim()
  return value && !/\s/u.test(value) ? value : ''
}

function nodeText(node: ElementNode): string {
  return (node.children || [])
    .filter((child): child is TextNode => child.type === 'text')
    .map(child => child.value)
    .join('')
}

function propertyString(node: ElementNode, property: string): string {
  const value = node.properties?.[property]
  return typeof value === 'string' ? value : ''
}

function replaceNode(parent: ElementNode | undefined, index: number | undefined, node: ElementNode | TextNode): void {
  if (!parent?.children || typeof index !== 'number') return
  parent.children[index] = node
}

function textNode(value: string): TextNode {
  return { type: 'text', value }
}
