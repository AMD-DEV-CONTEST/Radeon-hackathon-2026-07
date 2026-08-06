import { useState, useRef, type DragEvent, type ChangeEvent } from 'react'
import { ImageCubeIcon } from './icons'

interface UploadZoneProps {
  onFileSelect: (file: File) => void
  previewUrl?: string | null
}

export function UploadZone({ onFileSelect, previewUrl }: UploadZoneProps) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f && f.type.startsWith('image/')) onFileSelect(f)
  }

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) onFileSelect(f)
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onClick={() => inputRef.current?.click()}
      className={`
        group flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed
        bg-neutral-100/80 px-8 py-10 transition hover:border-neutral-500 hover:bg-neutral-50
        ${dragOver ? 'border-neutral-800 bg-neutral-50' : 'border-neutral-400'}
      `}
    >
      <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={handleChange} />

      {previewUrl ? (
        <img
          src={previewUrl}
          alt="Preview"
          className="mb-4 h-40 w-auto rounded-xl object-contain shadow-sm"
        />
      ) : (
        <ImageCubeIcon className="mb-5 h-24 w-24 text-neutral-400 transition group-hover:text-neutral-600" />
      )}

      <p className="text-base font-medium text-neutral-800">
        {previewUrl ? 'Click to change image' : 'Drag & drop an image here'}
      </p>
      <p className="mt-1 text-xs text-neutral-500">PNG, JPG up to 20MB</p>
    </div>
  )
}
