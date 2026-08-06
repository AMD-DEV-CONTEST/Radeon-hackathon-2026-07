async function handleResponse(response) {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || 'Request failed')
  }
  return response.json()
}

export const api = {
  health: () => fetch('/api/system/health').then(handleResponse),
  systemInfo: () => fetch('/api/system/info').then(handleResponse),
  benchmarks: () => fetch('/api/system/benchmarks').then(handleResponse),
  conversations: () => fetch('/api/conversations').then(handleResponse),
  conversation: (id) => fetch(`/api/conversations/${id}`).then(handleResponse),
  documents: () => fetch('/api/documents').then(handleResponse),
  sendMessage: (payload) =>
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(handleResponse),
  uploadDocument: (file) => {
    const form = new FormData()
    form.append('file', file)
    return fetch('/api/documents/upload', {
      method: 'POST',
      body: form,
    }).then(handleResponse)
  },
}
