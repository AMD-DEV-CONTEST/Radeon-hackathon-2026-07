import { FolderOpen, HardDrive, Link2, X } from "lucide-react";
import type { FormEvent } from "react";

interface LocalImportModalProps {
  open: boolean;
  path: string;
  suggestedFilename?: string;
  inputColorSpaceLabel: string;
  busy: boolean;
  onPathChange: (path: string) => void;
  onClose: () => void;
  onSubmit: () => void;
}

export function LocalImportModal({
  open,
  path,
  suggestedFilename,
  inputColorSpaceLabel,
  busy,
  onPathChange,
  onClose,
  onSubmit,
}: LocalImportModalProps) {
  if (!open) return null;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (path.trim() && !busy) onSubmit();
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="local-import-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="local-import-title"
      >
        <button
          className="modal-close"
          type="button"
          onClick={onClose}
          disabled={busy}
          aria-label="关闭本地路径导入"
        >
          <X size={15} />
        </button>

        <div className="local-import-heading">
          <div className="local-import-icon">
            <HardDrive size={19} />
          </div>
          <div>
            <span>LOCAL MEDIA</span>
            <h2 id="local-import-title">从本机路径导入大文件</h2>
            <p>适用于 ProRes、RAW 和数 GB 以上素材，不经过浏览器上传。</p>
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <label className="local-path-field">
            <span>视频绝对路径</span>
            <div>
              <FolderOpen size={15} />
              <input
                autoFocus
                value={path}
                onChange={(event) => onPathChange(event.target.value)}
                placeholder="C:\Users\你的用户名\Downloads\素材.mov"
                spellCheck={false}
                aria-describedby="local-import-hint"
              />
            </div>
          </label>

          <div className="local-import-details" id="local-import-hint">
            <div>
              <Link2 size={14} />
              <span>
                <strong>零拷贝优先</strong>
                同一磁盘建立硬链接；跨磁盘保留安全路径引用。
              </span>
            </div>
            <dl>
              <div>
                <dt>INPUT</dt>
                <dd>{inputColorSpaceLabel}</dd>
              </div>
              <div>
                <dt>FILE</dt>
                <dd>{suggestedFilename || "等待输入路径"}</dd>
              </div>
            </dl>
          </div>

          <div className="local-import-actions">
            <button
              className="button button-ghost"
              type="button"
              onClick={onClose}
              disabled={busy}
            >
              取消
            </button>
            <button
              className="button button-primary"
              type="submit"
              disabled={!path.trim() || busy}
            >
              {busy ? <span className="button-spinner" /> : <Link2 size={14} />}
              {busy ? "正在接入" : "开始导入"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
