// Toast - 入口 re-export 到 Radix Toast 实现(ui/toast + ui/use-toast + ui/toaster)。
// 旧 ToastKind/ToastMsg 类型保留,供页面 import;ToastStack 改由 App 用 useToast + Toaster 渲染。
export type { ToastKind, ToastMsg } from "./ui/use-toast";
export { Toaster } from "./ui/toaster";
