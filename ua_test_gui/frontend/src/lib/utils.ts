// cn:clsx + tailwind-merge,Shadcn 组件标准 className 合并工具。
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
