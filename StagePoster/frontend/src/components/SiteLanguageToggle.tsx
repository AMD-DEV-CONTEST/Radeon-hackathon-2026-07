import {useSiteLanguage} from '../hooks/useSiteLanguage';

export default function SiteLanguageToggle() {
  const {language, setLanguage} = useSiteLanguage();
  return <div className="site-language-toggle" role="group" aria-label="界面语言 / Interface language">
    <button type="button" className={language === 'zh' ? 'active' : ''} aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')}>中文</button>
    <button type="button" className={language === 'en' ? 'active' : ''} aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>EN</button>
  </div>;
}
