import {useRef, useState} from 'react';
import {CheckCircle2, ImagePlus, LoaderCircle, RefreshCw, Trash2} from 'lucide-react';
import type {UploadedAsset} from '../types';
import {useSiteLanguage} from '../hooks/useSiteLanguage';

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const MAX_IMAGE_EDGE = 1600;
const VALID_EXTENSIONS = /\.(png|jpe?g|webp|gif|svg)$/i;

function readAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('图片读取失败，请重新选择文件'));
    reader.readAsDataURL(file);
  });
}

async function prepareImage(file: File) {
  const source = await readAsDataUrl(file);
  if (file.type === 'image/svg+xml' || file.type === 'image/gif' || file.size < 700 * 1024) {
    return {dataUrl: source, type: file.type || 'image/png'};
  }

  const image = new Image();
  image.src = source;
  await image.decode();
  const scale = Math.min(1, MAX_IMAGE_EDGE / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext('2d');
  if (!context) throw new Error('浏览器无法处理这张图片');
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
  return {dataUrl: canvas.toDataURL('image/webp', 0.88), type: 'image/webp'};
}

interface Props {
  label: string;
  kind: UploadedAsset['category'];
  value?: UploadedAsset;
  onChange: (asset?: UploadedAsset) => void;
  required?: boolean;
}

export default function AssetUpload({label, kind, value, onChange, required = false}: Props) {
  const {english} = useSiteLanguage();
  const t = (zh: string, en: string) => english ? en : zh;
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const replaceRef = useRef<HTMLInputElement>(null);

  const pick = async (file?: File, input?: HTMLInputElement | null) => {
    if (!file) return;
    const isImage = file.type.startsWith('image/') || VALID_EXTENSIONS.test(file.name);
    if (!isImage) {
      onChange({id: crypto.randomUUID(), name: file.name, type: file.type, dataUrl: '', category: kind, status: 'error', error: t('仅支持 PNG、JPG、WEBP、GIF 或 SVG 图片', 'Only PNG, JPG, WEBP, GIF or SVG images are supported')});
      if (input) input.value = '';
      return;
    }
    if (file.size > MAX_FILE_SIZE) {
      onChange({id: crypto.randomUUID(), name: file.name, type: file.type, dataUrl: '', category: kind, status: 'error', error: t('图片不能超过 10MB', 'Image must be smaller than 10 MB')});
      if (input) input.value = '';
      return;
    }

    setBusy(true);
    try {
      const prepared = await prepareImage(file);
      onChange({id: crypto.randomUUID(), name: file.name, type: prepared.type, dataUrl: prepared.dataUrl, category: kind, status: 'success'});
    } catch (error) {
      onChange({id: crypto.randomUUID(), name: file.name, type: file.type, dataUrl: '', category: kind, status: 'error', error: error instanceof Error ? error.message : t('图片处理失败', 'Image processing failed')});
    } finally {
      setBusy(false);
      if (input) input.value = '';
    }
  };

  return <div className={`upload ${value?.status === 'error' ? 'upload-error' : ''}`}>
    <div className="upload-head">
      <span>{label}{required && <b> *</b>}</span>
      {busy && <em><LoaderCircle className="spin" size={14}/> {t('正在处理', 'Processing')}</em>}
      {!busy && value?.status === 'success' && <em><CheckCircle2 size={14}/> {t('已上传', 'Uploaded')}</em>}
    </div>
    {value?.dataUrl ? <div className="upload-preview">
      <img src={value.dataUrl} alt={label}/>
      <div><strong>{value.name}</strong><small>{value.type}</small></div>
    </div> : <label className="drop">
      <ImagePlus size={22}/><span>{busy ? t('正在处理图片…', 'Processing image…') : t('点击选择图片', 'Choose an image')}</span><small>PNG / JPG / WEBP / SVG · {t('最大 10MB', 'max 10 MB')}</small>
      <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml" disabled={busy} onChange={event => void pick(event.target.files?.[0], event.currentTarget)}/>
    </label>}
    {value?.error && <p className="field-error">{value.error}</p>}
    {value?.dataUrl && <div className="upload-actions">
      <label className={busy ? 'disabled' : ''}><RefreshCw size={14}/>{t('替换', 'Replace')}
        <input ref={replaceRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml" disabled={busy} onChange={event => void pick(event.target.files?.[0], event.currentTarget)}/>
      </label>
      <button type="button" disabled={busy} onClick={() => onChange()}><Trash2 size={14}/>{t('删除', 'Remove')}</button>
    </div>}
  </div>;
}
