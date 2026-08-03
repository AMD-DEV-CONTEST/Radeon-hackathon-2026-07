import type {PosterLanguage} from '../types';

export default function PosterLanguageToggle({value, onChange}: {
  value: PosterLanguage;
  onChange: (language: PosterLanguage) => void;
}) {
  return <div className="poster-language-toggle" role="group" aria-label="海报文案语言">
    <span>POSTER COPY</span>
    <button type="button" className={value === 'en' ? 'active' : ''} onClick={() => onChange('en')} aria-pressed={value === 'en'}>ENGLISH</button>
    <button type="button" className={value === 'zh' ? 'active' : ''} onClick={() => onChange('zh')} aria-pressed={value === 'zh'}>中文</button>
  </div>;
}
