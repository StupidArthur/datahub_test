import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

type ToastType = 'info' | 'success' | 'error'
interface ToastState {
  message: string
  type: ToastType
  visible: boolean
}

const ToastContext = createContext<(message: string, type?: ToastType) => void>(() => {})

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState>({ message: '', type: 'info', visible: false })

  const show = useCallback((message: string, type: ToastType = 'info') => {
    setToast({ message, type, visible: true })
    setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3200)
  }, [])

  // 语义色：成功绿 / 错误红 / 信息深炭灰
  const bg =
    toast.type === 'success'
      ? 'bg-[#2f9e6f]'
      : toast.type === 'error'
        ? 'bg-[#d44333]'
        : 'bg-[#37352f]'

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        className={`fixed bottom-6 left-1/2 -translate-x-1/2 px-5 py-2.5 rounded-lg text-white text-[13px] shadow-lg transition-all duration-300 z-[200] max-w-[80vw] break-words ${bg} ${
          toast.visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-5 pointer-events-none'
        }`}
      >
        {toast.message}
      </div>
    </ToastContext.Provider>
  )
}
