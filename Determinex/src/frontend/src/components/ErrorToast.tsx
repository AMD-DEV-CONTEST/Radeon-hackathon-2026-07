"use client";
import { createContext, useCallback, useContext, useRef, useState } from "react";

interface Toast {
  id: number;
  message: string;
}

interface ToastContextValue {
  showError: (msg: string) => void;
}

const ToastContext = createContext<ToastContextValue>({ showError: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const showError = useCallback((message: string) => {
    const id = ++nextId.current;
    setToasts((prev) => [...prev.slice(-4), { id, message }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5000);
  }, []);

  const dismiss = (id: number) => setToasts((prev) => prev.filter((t) => t.id !== id));

  return (
    <ToastContext.Provider value={{ showError }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[200] flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex items-start gap-3 bg-[#1a0a0a] border border-red-900/60 text-red-300 text-xs font-mono rounded-lg px-4 py-3 shadow-xl max-w-sm animate-in slide-in-from-right-5 duration-200"
          >
            <span className="text-red-500 mt-0.5 shrink-0">ERR</span>
            <span className="flex-1 break-words">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="text-red-600 hover:text-red-400 shrink-0 ml-1 text-sm leading-none"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useErrorToast() {
  return useContext(ToastContext).showError;
}
