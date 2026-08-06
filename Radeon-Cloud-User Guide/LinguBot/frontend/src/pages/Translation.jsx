import React, { useState, useEffect } from 'react';
import api from '../services/api';
import { 
  FiGlobe, FiArrowRight, FiCopy, FiDownload, FiStar, 
  FiTrash2, FiClock, FiCheck, FiChevronRight, FiAlertTriangle,
  FiMic, FiVolume2, FiMicOff
} from 'react-icons/fi';

const Translation = () => {
  const [text, setText] = useState('');
  const [sourceLang, setSourceLang] = useState('Auto-Detect');
  const [targetLang, setTargetLang] = useState('Spanish');
  const [translatedText, setTranslatedText] = useState('');
  const [detectedLang, setDetectedLang] = useState('');
  const [activeTab, setActiveTab] = useState('history'); // 'history' | 'favorites'
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [copied, setCopied] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [error, setError] = useState('');

  // 100+ languages list (109 total)
  const languages = [
    'Auto-Detect', 'Afrikaans', 'Albanian', 'Amharic', 'Arabic', 'Armenian', 'Azerbaijani',
    'Basque', 'Belarusian', 'Bengali', 'Bosnian', 'Bulgarian', 'Catalan', 'Cebuano', 'Chichewa',
    'Chinese', 'Corsican', 'Croatian', 'Czech', 'Danish', 'Dutch', 'English', 'Esperanto',
    'Estonian', 'Filipino', 'Finnish', 'French', 'Frisian', 'Galician', 'Georgian', 'German',
    'Greek', 'Gujarati', 'Haitian Creole', 'Hausa', 'Hawaiian', 'Hebrew', 'Hindi', 'Hmong',
    'Hungarian', 'Icelandic', 'Igbo', 'Indonesian', 'Irish', 'Italian', 'Japanese', 'Javanese',
    'Kannada', 'Kazakh', 'Khmer', 'Kinyarwanda', 'Korean', 'Kurdish', 'Kyrgyz', 'Lao', 'Latin',
    'Latvian', 'Lithuanian', 'Luxembourgish', 'Macedonian', 'Malagasy', 'Malay', 'Malayalam',
    'Maltese', 'Maori', 'Marathi', 'Mongolian', 'Myanmar', 'Nepali', 'Norwegian', 'Odia',
    'Pashto', 'Persian', 'Polish', 'Portuguese', 'Punjabi', 'Romanian', 'Russian', 'Samoan',
    'Scots Gaelic', 'Serbian', 'Sesotho', 'Shona', 'Sindhi', 'Sinhala', 'Slovak', 'Slovenian',
    'Somali', 'Spanish', 'Sundanese', 'Swahili', 'Swedish', 'Tajik', 'Tamil', 'Tatar', 'Telugu',
    'Thai', 'Turkish', 'Turkmen', 'Ukrainian', 'Urdu', 'Uyghur', 'Uzbek', 'Vietnamese', 'Welsh',
    'Xhosa', 'Yiddish', 'Yoruba', 'Zulu'
  ];

  // List of target languages (excludes Auto-Detect)
  const targetLanguages = languages.filter(l => l !== 'Auto-Detect');

  // Mapping language name to BCP-47 codes for Speech Web API
  const getLangCode = (langName) => {
    const codes = {
      'English': 'en-US', 'Spanish': 'es-ES', 'French': 'fr-FR', 'German': 'de-DE', 
      'Italian': 'it-IT', 'Portuguese': 'pt-PT', 'Chinese': 'zh-CN', 'Japanese': 'ja-JP', 
      'Korean': 'ko-KR', 'Arabic': 'ar-SA', 'Russian': 'ru-RU', 'Hindi': 'hi-IN', 
      'Bengali': 'bn-IN', 'Tamil': 'ta-IN', 'Telugu': 'te-IN', 'Vietnamese': 'vi-VN', 
      'Turkish': 'tr-TR', 'Dutch': 'nl-NL', 'Swahili': 'sw-KE', 'Swedish': 'sv-SE',
      'Polish': 'pl-PL', 'Greek': 'el-GR', 'Ukrainian': 'uk-UA', 'Thai': 'th-TH'
    };
    return codes[langName] || 'en-US';
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  const fetchHistory = async () => {
    try {
      const res = await api.get('/translation/history');
      setHistory(res.data);
    } catch (err) {
      console.error("Failed to load translation history", err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleTranslate = async (e) => {
    if (e) e.preventDefault();
    if (!text.trim()) return;

    setLoading(true);
    setError('');
    setTranslatedText('');

    try {
      const res = await api.post('/translation/translate', {
        text,
        sourceLanguage: sourceLang,
        targetLanguage: targetLang
      });
      setTranslatedText(res.data.translatedText);
      setDetectedLang(res.data.sourceLanguage);
      fetchHistory(); // Refresh history log
    } catch (err) {
      console.error("Translation error", err);
      setError("AI was unable to process this translation request.");
    } finally {
      setLoading(false);
    }
  };

  const handleSpeechInput = () => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Google Chrome or Microsoft Edge!");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = sourceLang === 'Auto-Detect' ? 'en-US' : getLangCode(sourceLang);
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognition.onerror = (e) => {
      console.error("Speech Recognition Error", e);
      setIsListening(false);
    };

    recognition.onresult = (event) => {
      const speechToText = event.results[0][0].transcript;
      setText(prev => prev + (prev ? ' ' : '') + speechToText);
    };

    recognition.start();
  };

  const handleSpeechOutput = () => {
    if (!translatedText) return;
    const synth = window.speechSynthesis;
    if (!synth) {
      alert("Text-to-speech output is not supported in this browser.");
      return;
    }
    const utterance = new SpeechSynthesisUtterance(translatedText);
    utterance.lang = getLangCode(targetLang);
    synth.speak(utterance);
  };

  const handleCopy = () => {
    if (!translatedText) return;
    navigator.clipboard.writeText(translatedText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!translatedText) return;
    const element = document.createElement("a");
    const file = new Blob([translatedText], { type: 'text/plain' });
    element.href = URL.createObjectURL(file);
    element.download = `translation_${targetLang.toLowerCase()}.txt`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const handleToggleFavorite = async (id, e) => {
    e.stopPropagation();
    try {
      const res = await api.put(`/translation/history/${id}/favorite`);
      // Update local state by toggling either isFavorite or favorite to be fully safe
      setHistory(history.map(item => {
        if (item.id === id) {
          const val = res.data.favorite !== undefined ? res.data.favorite : res.data.isFavorite;
          return { ...item, favorite: val, isFavorite: val };
        }
        return item;
      }));
    } catch (err) {
      console.error("Failed to toggle favorite status", err);
    }
  };

  const handleDeleteHistory = async (id, e) => {
    e.stopPropagation();
    if (!window.confirm("Delete this translation record?")) return;

    try {
      await api.delete(`/translation/history/${id}`);
      setHistory(history.filter(item => item.id !== id));
    } catch (err) {
      console.error("Failed to delete translation", err);
    }
  };

  const loadFromHistory = (item) => {
    setText(item.sourceText);
    setSourceLang(item.sourceLanguage);
    setTargetLang(item.targetLanguage);
    setTranslatedText(item.translatedText);
    setDetectedLang(item.sourceLanguage);
  };

  const filteredHistory = activeTab === 'favorites' 
    ? history.filter(item => item.favorite || item.isFavorite) 
    : history;

  return (
    <div className="space-y-6 text-left">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight text-gray-900 dark:text-white bg-gradient-to-r from-primary-600 to-violet-600 bg-clip-text text-transparent dark:from-primary-400 dark:to-violet-400">
          AI Translation
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-slate-400">
          Translate terms and documents into 100+ languages with browser Speech Input and Output.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/30 p-4 text-sm text-red-800 dark:text-red-400">
          <FiAlertTriangle className="h-5 w-5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Editor Panel Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div className="glass-panel rounded-2xl border border-gray-200 dark:border-slate-800 shadow-xl overflow-hidden flex flex-col bg-white/40 dark:bg-slate-900/30">
            
            {/* Header controls */}
            <div className="flex items-center justify-between border-b border-gray-200 dark:border-slate-800 bg-white/60 dark:bg-slate-900/50 p-3">
              <select
                value={sourceLang}
                onChange={(e) => setSourceLang(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-xs focus:outline-none text-gray-700 dark:text-slate-350"
              >
                {languages.map(l => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>

              <FiArrowRight className="text-gray-400 shrink-0" />

              <select
                value={targetLang}
                onChange={(e) => setTargetLang(e.target.value)}
                className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-800 bg-white dark:bg-slate-950 text-xs focus:outline-none text-gray-700 dark:text-slate-350"
              >
                {targetLanguages.map(l => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </div>

            {/* Split Editor Panes */}
            <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-gray-200 dark:divide-slate-800 min-h-[300px]">
              
              {/* Source Text Input */}
              <div className="flex flex-col p-4">
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  className="flex-1 w-full bg-transparent border-0 resize-none text-sm placeholder-gray-400 focus:outline-none text-gray-900 dark:text-white"
                  placeholder="Enter text to translate..."
                  rows={8}
                />
                
                <div className="flex justify-between items-center mt-3 pt-2 border-t border-gray-100/50 dark:border-slate-800/50 text-xs text-gray-400">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleSpeechInput}
                      title="Speak (Voice Dictation)"
                      className={`p-2 rounded-lg border transition ${
                        isListening 
                          ? 'bg-red-500 text-white border-red-500 animate-pulse'
                          : 'bg-white dark:bg-slate-950 border-gray-200 dark:border-slate-850 hover:bg-gray-100 text-gray-500'
                      }`}
                    >
                      {isListening ? <FiMicOff /> : <FiMic />}
                    </button>
                    <span>{text.length} characters</span>
                  </div>

                  <button
                    onClick={handleTranslate}
                    disabled={loading || !text.trim()}
                    className="bg-primary-600 hover:bg-primary-500 text-white font-semibold py-1.5 px-4 rounded-lg active:scale-95 transition disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-primary-500/10"
                  >
                    {loading ? 'Translating...' : 'Translate'}
                  </button>
                </div>
              </div>

              {/* Translation Output */}
              <div className="flex flex-col p-4 bg-gray-50/20 dark:bg-slate-950/10 justify-between">
                <div className="flex-1 text-sm text-left text-gray-900 dark:text-white whitespace-pre-wrap">
                  {translatedText || <span className="text-gray-400 italic">Translation will appear here...</span>}
                </div>

                {translatedText && (
                  <div className="flex justify-between items-center mt-4 pt-3 border-t border-gray-100 dark:border-slate-800">
                    <span className="text-[9px] text-gray-400 bg-gray-100 dark:bg-slate-800 px-2 py-0.5 rounded-full uppercase tracking-wider font-bold">
                      Detected: {detectedLang}
                    </span>
                    
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={handleSpeechOutput}
                        title="Listen (Text to Speech)"
                        className="p-2 rounded bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-850 text-gray-500 hover:text-primary-600 transition"
                      >
                        <FiVolume2 />
                      </button>

                      <button
                        onClick={handleCopy}
                        title="Copy to Clipboard"
                        className="p-2 rounded bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-850 text-gray-500 hover:text-primary-600 transition"
                      >
                        {copied ? <FiCheck className="text-green-500" /> : <FiCopy />}
                      </button>

                      <button
                        onClick={handleDownload}
                        title="Download Text File"
                        className="p-2 rounded bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-850 text-gray-500 hover:text-primary-600 transition"
                      >
                        <FiDownload />
                      </button>
                    </div>
                  </div>
                )}
              </div>

            </div>
          </div>
        </div>

        {/* History & Favorites Panel (Right) */}
        <div className="lg:col-span-1 space-y-6">
          <div className="glass-panel p-6 rounded-2xl shadow-xl flex flex-col h-[460px] bg-white/40 dark:bg-slate-900/30">
            
            {/* Tabs */}
            <div className="flex border-b border-gray-100 dark:border-slate-800 pb-3 mb-4 gap-4">
              <button
                onClick={() => setActiveTab('history')}
                className={`text-sm font-bold pb-1.5 transition ${
                  activeTab === 'history'
                    ? 'text-primary-600 dark:text-primary-400 border-b-2 border-primary-600'
                    : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                History
              </button>
              <button
                onClick={() => setActiveTab('favorites')}
                className={`text-sm font-bold pb-1.5 transition ${
                  activeTab === 'favorites'
                    ? 'text-primary-600 dark:text-primary-400 border-b-2 border-primary-600'
                    : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                Starred
              </button>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-slate-850/50 pr-1">
              {loadingHistory ? (
                <div className="flex justify-center py-10">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-t-primary-600 border-primary-100"></div>
                </div>
              ) : filteredHistory.length === 0 ? (
                <p className="text-xs text-gray-400 py-10 text-center">No translations recorded.</p>
              ) : (
                filteredHistory.map((item) => {
                  const starred = item.favorite || item.isFavorite;
                  return (
                    <div
                      key={item.id}
                      onClick={() => loadFromHistory(item)}
                      className="p-3 text-left hover:bg-gray-100/50 dark:hover:bg-slate-900/10 cursor-pointer transition rounded-xl my-1.5 flex justify-between items-start gap-2 border border-transparent hover:border-gray-200/20"
                    >
                      <div className="overflow-hidden">
                        <p className="text-xs font-bold text-gray-800 dark:text-slate-200 truncate">
                          {item.sourceText}
                        </p>
                        <p className="text-[10px] text-gray-400 truncate mt-1">
                          {item.translatedText}
                        </p>
                        <div className="flex items-center gap-1.5 mt-2 text-[8px] text-gray-400 font-extrabold uppercase">
                          <span>{item.sourceLanguage}</span>
                          <FiChevronRight />
                          <span className="text-primary-500">{item.targetLanguage}</span>
                        </div>
                      </div>
                      
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={(e) => handleToggleFavorite(item.id, e)}
                          className={`p-1.5 rounded transition hover:bg-gray-100 dark:hover:bg-slate-800 ${
                            starred ? 'text-yellow-500' : 'text-gray-400'
                          }`}
                        >
                          <FiStar className="h-3.5 w-3.5" fill={starred ? "currentColor" : "none"} />
                        </button>

                        <button
                          onClick={(e) => handleDeleteHistory(item.id, e)}
                          className="p-1.5 rounded text-gray-400 hover:text-red-500 hover:bg-gray-100 dark:hover:bg-slate-800 transition"
                        >
                          <FiTrash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

          </div>
        </div>

      </div>
    </div>
  );
};

export default Translation;
