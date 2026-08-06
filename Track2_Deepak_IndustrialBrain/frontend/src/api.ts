import { Session, DashboardData, DocumentRecord, ChatAnswer, AnswerFormat, AssetData, RcaData, AnalyticsData } from './types';

const API_BASE = '/api';

function getAuthHeaders() {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {})
  };
}

async function fetchApi<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  
  const headers: Record<string, string> = {};
  const token = localStorage.getItem('token');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (!isFormData) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: { ...headers, ...(options.headers as any) }
  });

  if (!res.ok) {
    throw new Error(`API Error: ${res.statusText}`);
  }

  // Handle binary download
  const contentType = res.headers.get('content-type');
  if (contentType && contentType.includes('application/vnd.openxmlformats-officedocument.wordprocessingml.document')) {
    return res.blob() as any;
  }

  return res.json();
}

export const api = {
  login: (credentials: any) => fetchApi<Session>('/auth/login', { method: 'POST', body: JSON.stringify(credentials) }),
  getDashboard: () => fetchApi<DashboardData>('/dashboard'),
  uploadDocument: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return fetchApi<any>('/documents/upload', { method: 'POST', body: formData });
  },
  getDocuments: () => fetchApi<DocumentRecord[]>('/documents'),
  deleteDocument: (id: string) => fetchApi<any>(`/documents/${id}`, { method: 'DELETE' }),
  chatQuery: (payload: { question: string, assetTag?: string, desiredFormat: AnswerFormat, history: any[] }) => 
    fetchApi<ChatAnswer>('/chat/query', { method: 'POST', body: JSON.stringify(payload) }),
  chatFeedback: (id: string, feedback: 1 | -1 | null) => fetchApi<any>(`/chat/${id}/feedback`, { method: 'PATCH', body: JSON.stringify({ feedback }) }),
  getAsset: (tag: string) => fetchApi<AssetData>(`/assets/${tag}`),
  generateRca: (tag: string) => fetchApi<RcaData>(`/rca/${tag}`, { method: 'POST' }),
  exportRca: async (tag: string) => {
    const blob = await fetchApi<Blob>(`/rca/export/${tag}`);
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `RCA_${tag}.docx`;
    a.click();
  },
  getAnalytics: () => fetchApi<AnalyticsData>('/analytics')
};
