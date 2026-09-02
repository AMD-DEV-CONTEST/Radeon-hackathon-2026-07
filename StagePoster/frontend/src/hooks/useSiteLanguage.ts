import {useCallback, useEffect, useState} from 'react';

export type SiteLanguage = 'zh' | 'en';
const STORAGE_KEY = 'poster-site-language';
const EVENT_NAME = 'poster-site-language-change';

function readLanguage(): SiteLanguage {
  return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh';
}

export function useSiteLanguage() {
  const [language, setLanguageState] = useState<SiteLanguage>(readLanguage);
  useEffect(() => {
    const sync = () => setLanguageState(readLanguage());
    window.addEventListener('storage', sync);
    window.addEventListener(EVENT_NAME, sync);
    return () => {
      window.removeEventListener('storage', sync);
      window.removeEventListener(EVENT_NAME, sync);
    };
  }, []);
  const setLanguage = useCallback((next: SiteLanguage) => {
    localStorage.setItem(STORAGE_KEY, next);
    setLanguageState(next);
    window.dispatchEvent(new Event(EVENT_NAME));
  }, []);
  return {language, setLanguage, english: language === 'en'};
}
