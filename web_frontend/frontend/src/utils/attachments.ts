import type { RuntimeAttachmentInput } from '@/types/protocol'

export const MAX_RUNTIME_ATTACHMENTS = 9

export async function runtimeFileAttachmentFromFile(
  file: File,
  options: { name?: string } = {}
): Promise<RuntimeAttachmentInput> {
  const content = await readFileAsBase64(file)
  return {
    kind: 'file',
    name: options.name || file.name,
    content,
    encoding: 'base64',
    mime_type: file.type || undefined,
  }
}

export function pastedImageFiles(event: ClipboardEvent, fallbackName: (file: File, index: number) => string): File[] {
  const items = Array.from(event.clipboardData?.items || [])
  const files: File[] = []
  for (const item of items) {
    if (item.kind !== 'file' || !item.type.startsWith('image/')) continue
    const file = item.getAsFile()
    if (!file) continue
    files.push(
      file.name
        ? file
        : new File([file], fallbackName(file, files.length), { type: file.type, lastModified: file.lastModified })
    )
  }
  return files
}

export function extensionFromMimeType(mimeType: string): string {
  const subtype = mimeType.split('/')[1]?.split(';')[0]?.trim().toLowerCase()
  if (!subtype) return 'png'
  if (subtype === 'jpeg') return 'jpg'
  if (!subtype.includes('+')) return subtype
  return subtype.slice(0, subtype.indexOf('+')) || 'png'
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const separatorIndex = result.indexOf(',')
      resolve(separatorIndex >= 0 ? result.slice(separatorIndex + 1) : result)
    }
    reader.onerror = () => reject(reader.error || new Error('failed to read attachment file'))
    reader.readAsDataURL(file)
  })
}
