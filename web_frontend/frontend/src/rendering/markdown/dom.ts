import mermaid from 'mermaid'

let mermaidInitialized = false

export async function enhanceRenderedMarkdown(root: ParentNode | null): Promise<void> {
  if (!root) return
  await renderMermaidDiagrams(root)
}

async function renderMermaidDiagrams(root: ParentNode): Promise<void> {
  const nodes = Array.from(root.querySelectorAll<HTMLElement>('.mermaid:not([data-processed="true"])'))
  if (nodes.length === 0) return
  if (!mermaidInitialized) {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'neutral',
    })
    mermaidInitialized = true
  }
  nodes.forEach((node) => {
    node.dataset.processed = 'true'
  })
  try {
    await mermaid.run({ nodes })
  } catch (err) {
    console.error('Mermaid render error:', err)
  }
}
