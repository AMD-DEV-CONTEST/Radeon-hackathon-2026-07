// ============================================================================
// Dify Knowledge Base API Client
// 将 qa-system 的知识条目推送到 Dify 知识库
// Dify API: https://docs.dify.ai/api-reference/knowledge-bases
// ============================================================================

const DIFY_BASE_URL = process.env.DIFY_BASE_URL || "";     // https://your-domain/v1
const DIFY_API_KEY = process.env.DIFY_API_KEY || "";        // dataset-xxx
const DIFY_DATASET_NAME = process.env.DIFY_DATASET_NAME || "电商客服知识库";

export interface DifyDataset {
  id: string;
  name: string;
  description: string;
  document_count: number;
}

export interface DifyDocument {
  id: string;
  name: string;
  indexing_status: string;
  enabled: boolean;
}

export interface DifyPushResult {
  dataset_id: string;
  dataset_name: string;
  total: number;
  succeeded: number;
  failed: number;
  errors: string[];
  documents: Array<{ knowledge_id: string; document_id: string; batch: string }>;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  isFormData?: boolean,
): Promise<T> {
  if (!DIFY_BASE_URL || !DIFY_API_KEY) {
    throw new Error("DIFY_BASE_URL and DIFY_API_KEY must be set");
  }

  const url = `${DIFY_BASE_URL.replace(/\/+$/, "")}${path}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${DIFY_API_KEY}`,
  };
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, {
    method,
    headers,
    body: body ? (isFormData ? body as FormData : JSON.stringify(body)) : undefined,
  });

  if (!res.ok) {
    const err = await res.text().catch(() => "");
    throw new Error(`Dify API ${res.status}: ${err.slice(0, 200)}`);
  }

  return res.json() as Promise<T>;
}

/** Create an empty knowledge base */
export async function createDataset(
  name: string,
  description?: string,
): Promise<DifyDataset> {
  const result = await request<DifyDataset>("POST", "/datasets", {
    name,
    description: description || "",
    indexing_technique: "high_quality",
    permission: "all_team_members",
  });
  return result;
}

/** List existing datasets (Dify Knowledge API returns list via GET /datasets) */
export async function listDatasets(): Promise<DifyDataset[]> {
  try {
    const result = await request<{ data: DifyDataset[] }>("GET", "/datasets");
    return result.data || [];
  } catch {
    // Some Dify versions return array directly
    const result = await request<DifyDataset[]>("GET", "/datasets");
    return result || [];
  }
}

/** Find or create a dataset by name */
export async function ensureDataset(
  name: string = DIFY_DATASET_NAME,
  description?: string,
): Promise<DifyDataset> {
  const datasets = await listDatasets();
  const existing = datasets.find((d) => d.name === name);
  if (existing) return existing;
  return createDataset(name, description);
}

/** Create a document from text content */
export async function createDocumentByText(
  datasetId: string,
  name: string,
  text: string,
): Promise<{ document: DifyDocument; batch: string }> {
  const result = await request<{ document: DifyDocument; batch: string }>(
    "POST",
    `/datasets/${datasetId}/document/create-by-text`,
    {
      name,
      text,
      indexing_technique: "high_quality",
      doc_form: "text_model",
      process_rule: { mode: "automatic" },
    },
  );
  return result;
}

/** Check document indexing status */
export async function getIndexingStatus(
  datasetId: string,
  batch: string,
): Promise<{ documents: DifyDocument[] }> {
  const result = await request<{ documents: DifyDocument[] }>(
    "GET",
    `/datasets/${datasetId}/documents/${batch}/indexing-status`,
  );
  return result;
}

/** Push knowledge entries from qa-system to Dify dataset
 *  @param entries - array of { title, content, category }
 *  @param onProgress - callback per entry
 */
export async function pushKnowledgeEntries(
  entries: Array<{ knowledge_id?: string; title: string; content: string; category?: string }>,
  onProgress?: (current: number, total: number, title: string, status: string) => void,
): Promise<DifyPushResult> {
  const total = entries.length;
  const result: DifyPushResult = {
    dataset_id: "",
    dataset_name: DIFY_DATASET_NAME,
    total,
    succeeded: 0,
    failed: 0,
    errors: [],
    documents: [],
  };

  if (total === 0) return result;

  // Ensure dataset exists
  const dataset = await ensureDataset();
  result.dataset_id = dataset.id;

  for (let i = 0; i < total; i++) {
    const entry = entries[i];
    const title = entry.title || `知识条目 ${i + 1}`;
    try {
      const docName = `[${entry.category || "faq"}] ${title}`;
      const created = await createDocumentByText(dataset.id, docName, entry.content);
      if (entry.knowledge_id) {
        result.documents.push({
          knowledge_id: entry.knowledge_id,
          document_id: created.document.id,
          batch: created.batch,
        });
      }
      result.succeeded++;
      onProgress?.(i + 1, total, title, "ok");
    } catch (err) {
      result.failed++;
      const msg = err instanceof Error ? err.message : String(err);
      result.errors.push(`${title}: ${msg}`);
      onProgress?.(i + 1, total, title, `fail: ${msg}`);
    }
  }

  return result;
}
