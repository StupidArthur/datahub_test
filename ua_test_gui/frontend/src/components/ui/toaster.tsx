// Toaster:渲染 useToast 队列。点击/自动关闭(duration=3s)对齐旧交互。
import { Toast, ToastClose, ToastProvider, ToastViewport } from "./toast";
import type { ToastMsg } from "./use-toast";

export function Toaster({ toasts, dismiss }: { toasts: ToastMsg[]; dismiss: (id: number) => void }) {
  return (
    <ToastProvider duration={3000} swipeDirection="right">
      {toasts.map((t) => (
        <Toast
          key={t.id}
          variant={t.kind}
          onOpenChange={(open) => {
            if (!open) dismiss(t.id);
          }}
          onClick={() => dismiss(t.id)}
        >
          <span>{t.text}</span>
          <ToastClose />
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
