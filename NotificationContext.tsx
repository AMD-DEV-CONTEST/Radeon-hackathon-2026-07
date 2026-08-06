import React, { createContext, useContext, useState, useCallback } from 'react';

export type ToastType = 'success' | 'error' | 'info' | 'achievement';

export interface Toast {
  id: string;
  message: string;
  type: ToastType;
  title?: string;
}

interface NotificationContextType {
  toasts: Toast[];
  showToast: (message: string, type: ToastType, title?: string) => void;
  removeToast: (id: string) => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

export const NotificationProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const showToast = useCallback((message: string, type: ToastType, title?: string) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts(prev => [...prev, { id, message, type, title }]);

    // Auto-remove toasts after 4 seconds (achievement toast stays for 6 seconds)
    const duration = type === 'achievement' ? 6000 : 4000;
    setTimeout(() => {
      removeToast(id);
    }, duration);
  }, [removeToast]);

  return (
    <NotificationContext.Provider value={{ toasts, showToast, removeToast }}>
      {children}
      {/* Toast Render Panel */}
      <div className="fixed bottom-5 right-5 z-[9999] flex flex-col gap-3 max-w-sm w-full">
        {toasts.map(toast => (
          <div
            key={toast.id}
            onClick={() => removeToast(toast.id)}
            className={`cursor-pointer p-4 rounded-xl shadow-2xl backdrop-blur-md border animate-fade-in transition-all hover:scale-102 flex flex-col gap-1 ${
              toast.type === 'success'
                ? 'bg-emerald-950/80 border-emerald-500/30 text-emerald-200'
                : toast.type === 'error'
                ? 'bg-rose-950/80 border-rose-500/30 text-rose-200'
                : toast.type === 'achievement'
                ? 'bg-indigo-950/90 border-yellow-500/40 text-indigo-100 ring-2 ring-yellow-500/20'
                : 'bg-dark-900/80 border-primary-500/30 text-primary-200'
            }`}
          >
            {toast.type === 'achievement' && (
              <div className="flex items-center gap-2 text-yellow-400 font-semibold text-xs tracking-wider uppercase">
                👑 Achievement Unlocked!
              </div>
            )}
            {toast.title && <div className="font-bold font-heading text-sm">{toast.title}</div>}
            <div className="text-xs font-medium leading-relaxed">{toast.message}</div>
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  );
};

export const useNotification = () => {
  const context = useContext(NotificationContext);
  if (!context) throw new Error('useNotification must be used within a NotificationProvider');
  return context;
};
