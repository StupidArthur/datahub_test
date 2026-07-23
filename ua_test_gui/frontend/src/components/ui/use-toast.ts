// useToast:管理 toast 队列,保持旧 pushToast(kind, text) + 自动消失 + 点击关闭 行为。
import * as React from "react";

// toast 样式变体(对齐 toast.tsx 的 success/error/info),直接枚举避免跨文件 cva 类型耦合。
export type ToastKind = "success" | "error" | "info";

export interface ToastMsg {
  id: number;
  kind: ToastKind;
  text: string;
}

// 简单全局队列(useToast 在 App 调一次,通过返回的 push 传给各页)。
let count = 0;

export function useToast() {
  const [toasts, setToasts] = React.useState<ToastMsg[]>([]);

  const push = React.useCallback((kind: ToastKind, text: string) => {
    const id = ++count;
    setToasts((t) => [...t, { id, kind, text }]);
  }, []);

  const dismiss = React.useCallback((id: number) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  return { toasts, push, dismiss };
}
