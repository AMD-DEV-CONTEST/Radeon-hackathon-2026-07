import { useRef, useState, type ChangeEvent } from "react";
import {
  humanizeNetworkError,
  recognizeInventoryImage,
  type InventoryDraftItem
} from "../api";

type InventoryImageIntakeProps = {
  busy: boolean;
  confirmationPending: boolean;
  operable: boolean;
  onSendToAgent: (text: string) => void;
};

type IntakeStage = "idle" | "reading" | "recognizing" | "ready" | "error";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

export function InventoryImageIntake({
  busy,
  confirmationPending,
  operable,
  onSendToAgent
}: InventoryImageIntakeProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [stage, setStage] = useState<IntakeStage>("idle");
  const [imageDataUrl, setImageDataUrl] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<InventoryDraftItem[]>([]);
  const [limitations, setLimitations] = useState<string[]>([]);
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function chooseImage(): void {
    inputRef.current?.click();
  }

  async function onFileChange(
    event: ChangeEvent<HTMLInputElement>
  ): Promise<void> {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;

    setError(null);
    setDrafts([]);
    setLimitations([]);
    setSelectedDraftId(null);
    setFileName(file.name);
    setImageDataUrl(null);
    if (!IMAGE_TYPES.includes(file.type)) {
      setStage("error");
      setError("只支持 JPEG、PNG 或 WebP 图片。");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setStage("error");
      setError("图片超过 5 MB 限制，请压缩后重试。");
      return;
    }

    setStage("reading");
    try {
      const dataUrl = await fileToDataUrl(file);
      setImageDataUrl(dataUrl);
      setStage("recognizing");
      const result = await recognizeInventoryImage(dataUrl);
      setDrafts(result.items);
      setLimitations(result.limitations);
      setSelectedDraftId(result.items.length === 1 ? result.items[0]!.id : null);
      setStage("ready");
    } catch (requestError) {
      setStage("error");
      setError(humanizeNetworkError(requestError));
    }
  }

  function updateDraft(
    id: string,
    patch: Partial<InventoryDraftItem>
  ): void {
    setDrafts((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, ...patch } : draft))
    );
  }

  function sendSelectedDraft(): void {
    const selected = drafts.find((draft) => draft.id === selectedDraftId);
    if (!selected?.rawName.trim()) return;
    const quantity =
      selected.quantity == null
        ? "数量待确认的"
        : `${selected.quantity}${selected.unit ?? ""}`;
    onSendToAgent(
      `冰箱照片识别到${quantity}${selected.rawName}，请先预览入库，不要直接写入。`
    );
  }

  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId);
  const canSend =
    selectedDraft != null &&
    Boolean(selectedDraft.rawName.trim()) &&
    operable &&
    !busy &&
    !confirmationPending &&
    stage === "ready";

  return (
    <section className="inventory-image-intake" aria-labelledby="inventory-image-title">
      <div className="intake-section-heading">
        <div>
          <h3 id="inventory-image-title">照片识别</h3>
          <p className="muted compact-line">只生成识别草稿，不会直接写入库存。</p>
        </div>
        <button
          className="intake-trigger"
          type="button"
          disabled={busy || confirmationPending || stage === "recognizing"}
          onClick={chooseImage}
        >
          拍照识别
        </button>
      </div>
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        capture="environment"
        onChange={(event) => void onFileChange(event)}
        aria-label="选择冰箱或食材照片"
      />

      {imageDataUrl ? (
        <div className="intake-image-preview">
          <img src={imageDataUrl} alt={`${fileName ?? "照片"}预览`} />
          <div className="muted intake-file-name">{fileName}</div>
        </div>
      ) : null}

      {stage === "reading" ? (
        <p className="intake-progress" role="status">正在读取照片…</p>
      ) : null}
      {stage === "recognizing" ? (
        <p className="intake-progress" role="status">正在让 Gemma 4 查看照片…</p>
      ) : null}
      {stage === "error" ? (
        <div className="intake-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={chooseImage}>
            重试
          </button>
        </div>
      ) : null}

      {stage === "ready" ? (
        <div className="intake-draft-area">
          <div className="intake-draft-title">
            <strong>识别草稿，需要确认</strong>
            <span className="tag">模型观察结果</span>
          </div>
          {drafts.length > 1 ? (
            <p className="intake-selection-note" role="status">
              当前一次预览一项，请选择要处理的物品。
            </p>
          ) : null}
          {drafts.length === 0 ? (
            <p className="empty-state">照片中没有返回可确认的食品项目。</p>
          ) : (
            <div className="intake-draft-list">
              {drafts.map((draft) => (
                <div
                  className={`intake-draft-row ${
                    selectedDraftId === draft.id ? "selected" : ""
                  }`}
                  key={draft.id}
                >
                  <label className="intake-draft-select">
                    <input
                      type="radio"
                      name="inventory-draft-selection"
                      checked={selectedDraftId === draft.id}
                      onChange={() => setSelectedDraftId(draft.id)}
                      disabled={busy || confirmationPending}
                    />
                    <span>选择此项</span>
                  </label>
                  <label>
                    <span className="intake-field-label">名称</span>
                    <input
                      type="text"
                      value={draft.rawName}
                      onChange={(event) =>
                        updateDraft(draft.id, { rawName: event.target.value })
                      }
                      disabled={busy || confirmationPending}
                    />
                  </label>
                  <div className="intake-field-grid">
                    <label>
                      <span className="intake-field-label">数量</span>
                      <input
                        type="number"
                        min="0"
                        step="any"
                        value={draft.quantity ?? ""}
                        placeholder="待确认"
                        onChange={(event) =>
                          updateDraft(draft.id, {
                              quantity:
                                parseQuantity(event.target.value)
                          })
                        }
                        disabled={busy || confirmationPending}
                      />
                    </label>
                    <label>
                      <span className="intake-field-label">单位</span>
                      <input
                        type="text"
                        value={draft.unit ?? ""}
                        placeholder="待确认"
                        onChange={(event) =>
                          updateDraft(draft.id, {
                            unit: event.target.value || null
                          })
                        }
                        disabled={busy || confirmationPending}
                      />
                    </label>
                  </div>
                  <div className="intake-draft-meta">
                    <span className={`tag confidence-${draft.confidence}`}>
                      置信度：{draft.confidence}
                    </span>
                    <span className="muted">依据：{draft.evidence}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
          {limitations.length > 0 ? (
            <div className="intake-limitations">
              <strong>看不清的部分</strong>
              <ul>
                {limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <button
            className="primary intake-agent-button"
            type="button"
            disabled={!canSend}
            onClick={sendSelectedDraft}
          >
            交给 Agent 预览入库
          </button>
          {!operable ? (
            <p className="muted intake-blocked-note">
              Agent 当前未连接，先完成编辑；连接模型后才能提交预览。
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") resolve(reader.result);
      else reject(new Error("照片读取失败。"));
    };
    reader.onerror = () => reject(new Error("照片读取失败。"));
    reader.readAsDataURL(file);
  });
}

function parseQuantity(value: string): number | null {
  if (!value.trim()) return null;
  const quantity = Number(value);
  return Number.isFinite(quantity) && quantity > 0 ? quantity : null;
}
