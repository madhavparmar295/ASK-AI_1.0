import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const ToastContext = createContext(() => {})

/** Short messages at the bottom of the screen. Announced to screen readers. */
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, tone = 'success') => {
    const id = Math.random().toString(36).slice(2)
    setItems((l) => [...l, { id, message, tone }])
    setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), 4500)
  }, [])
  const value = useMemo(() => push, [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-50 flex flex-col items-center gap-2 px-4 sm:bottom-6">
        {items.map((t) => (
          <div key={t.id} className={`pointer-events-auto rounded-xl px-4 py-2 text-sm text-white shadow-lg ${t.tone === 'error' ? 'bg-red-600' : 'bg-purple-700'}`}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
