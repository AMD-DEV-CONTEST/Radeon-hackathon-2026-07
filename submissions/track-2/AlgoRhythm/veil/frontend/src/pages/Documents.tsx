import { useRef, useState } from 'react'
import { useApp } from '@/context/AppContext'
import { api } from '@/lib/api'
import { RiskBadge } from '@/components/ui/Badge'
import { EmptyState } from '@/components/ui/EmptyState'
import { FileText, Upload, ArrowRight, X } from 'lucide-react'
import { cn, formatUtility, formatDate } from '@/lib/utils'
import { now } from '@/lib/utils'
import type { DocumentRecord } from '@/types'
import { motion, AnimatePresence } from 'framer-motion'

export function DocumentsPage() {
  const { auth, documents, addDocument, setSelectedDocumentId, setCurrentPage } = useApp()
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')

  if (!auth) return null

  const canUpload = auth.role === 'auditor'

  async function doUpload(file: File) {
    if (!file) return
    setUploading(true)
    setUploadError('')
    try {
      const res = await api.uploadDocument(file)
      const doc: DocumentRecord = {
        document_id: res.document_id,
        filename: res.filename,
        char_count: res.char_count,
        word_count: res.word_count,
        pages: res.pages,
        uploadedAt: now(),
        status: 'uploaded',
      }
      addDocument(doc)
      setSelectedFile(null)
    } catch (err: unknown) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (f) setSelectedFile(f)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files?.[0]
    if (f) setSelectedFile(f)
  }

  function openAudit(doc: DocumentRecord) {
    setSelectedDocumentId(doc.document_id)
    setCurrentPage('audit')
  }

  return (
    <div className="max-w-5xl mx-auto px-8 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Documents</h1>
          <p className="text-sm text-gray-500 mt-1">Manage uploaded documents and audit results</p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Upload panel */}
        <div className="col-span-1">
          <div className="bg-white border border-gray-200 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-900 mb-4">Upload document</h2>

            {canUpload ? (
              <>
                {/* Drop zone */}
                <div
                  onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileRef.current?.click()}
                  className={cn(
                    'border-2 border-dashed rounded-md p-6 text-center cursor-pointer transition-colors',
                    dragOver
                      ? 'border-gray-400 bg-gray-50'
                      : selectedFile
                      ? 'border-gray-300 bg-gray-50'
                      : 'border-gray-200 hover:border-gray-300',
                  )}
                >
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".pdf,.docx,.txt,.md"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                  {selectedFile ? (
                    <div>
                      <FileText size={20} className="mx-auto text-gray-500 mb-2" />
                      <p className="text-xs font-medium text-gray-700 truncate">{selectedFile.name}</p>
                      <p className="text-2xs text-gray-400 mt-0.5">
                        {(selectedFile.size / 1024).toFixed(0)} KB
                      </p>
                    </div>
                  ) : (
                    <div>
                      <Upload size={20} className="mx-auto text-gray-300 mb-2" />
                      <p className="text-xs text-gray-500">Drop file here or click to browse</p>
                      <p className="text-2xs text-gray-400 mt-1">PDF · DOCX · TXT · MD</p>
                    </div>
                  )}
                </div>

                {selectedFile && (
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => doUpload(selectedFile)}
                      disabled={uploading}
                      className={cn(
                        'flex-1 py-2 px-3 text-sm font-medium rounded-md transition-colors',
                        'bg-gray-900 text-white hover:bg-gray-800',
                        'disabled:opacity-50 disabled:cursor-not-allowed',
                      )}
                    >
                      {uploading ? 'Uploading…' : 'Upload'}
                    </button>
                    <button
                      onClick={() => setSelectedFile(null)}
                      disabled={uploading}
                      className="p-2 text-gray-400 hover:text-gray-600 rounded-md hover:bg-gray-100 transition-colors"
                    >
                      <X size={14} />
                    </button>
                  </div>
                )}

                {uploadError && (
                  <p className="mt-2 text-xs text-red-600">{uploadError}</p>
                )}
              </>
            ) : (
              <div className="text-center py-6">
                <p className="text-sm text-gray-500">Upload requires Auditor role.</p>
              </div>
            )}
          </div>

          {/* Format support */}
          <div className="mt-3 bg-white border border-gray-200 rounded-lg p-4">
            <p className="section-label mb-3">Supported formats</p>
            <div className="space-y-1.5">
              {[
                ['PDF', 'pdfminer extraction'],
                ['DOCX', 'python-docx'],
                ['TXT', 'plain text'],
                ['MD', 'markdown'],
              ].map(([ext, note]) => (
                <div key={ext} className="flex items-center justify-between">
                  <span className="text-xs font-mono text-gray-700">.{ext.toLowerCase()}</span>
                  <span className="text-2xs text-gray-400">{note}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Document list */}
        <div className="col-span-2">
          {documents.length === 0 ? (
            <div className="bg-white border border-gray-200 rounded-lg">
              <EmptyState
                icon={<FileText />}
                title="No documents"
                description={canUpload ? "Upload a document to begin an adversarial privacy audit." : "No documents have been uploaded yet."}
              />
            </div>
          ) : (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 flex items-center">
                <span className="section-label">{documents.length} document{documents.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="divide-y divide-gray-100">
                <AnimatePresence initial={false}>
                  {documents.map(doc => (
                    <DocumentRow
                      key={doc.document_id}
                      doc={doc}
                      onClick={() => openAudit(doc)}
                    />
                  ))}
                </AnimatePresence>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function DocumentRow({ doc, onClick }: { doc: DocumentRecord; onClick: () => void }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-4 px-4 py-3.5 hover:bg-gray-50 cursor-pointer transition-colors group"
      onClick={onClick}
    >
      <FileText size={15} className="text-gray-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-2xs text-gray-400 font-mono">
            {doc.word_count.toLocaleString()}w · {doc.pages}p
          </span>
          <span className="text-2xs text-gray-300">·</span>
          <span className="text-2xs text-gray-400 font-mono">
            {formatDate(doc.uploadedAt)}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {doc.lastBand ? (
          <RiskBadge band={doc.lastBand} />
        ) : (
          <span className="text-2xs text-gray-400">Not audited</span>
        )}
        {doc.lastUtility != null && (
          <span className="text-xs text-gray-400 font-mono tabular-nums">
            {formatUtility(doc.lastUtility)}
          </span>
        )}
        <ArrowRight size={13} className="text-gray-300 group-hover:text-gray-500 transition-colors" />
      </div>
    </motion.div>
  )
}
