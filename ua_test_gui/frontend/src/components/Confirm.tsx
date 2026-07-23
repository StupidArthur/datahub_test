// Confirm - 二次确认对话框(Radix Dialog),接口与旧版完全一致:
// open/title/children/onOk/onCancel/okText/cancelText/danger。交互不变(点遮罩/ESC=取消)。
import React from "react";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "./ui/dialog";
import { Button } from "./ui/button";

export function Confirm({
  open, title, children, onOk, onCancel, okText, cancelText, danger,
}: {
  open: boolean;
  title: string;
  children?: React.ReactNode;
  onOk: () => void;
  onCancel: () => void;
  okText?: string;
  cancelText?: string;
  danger?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="max-w-md">
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription asChild>
          <div className="leading-relaxed">{children}</div>
        </DialogDescription>
        <div className="flex justify-end gap-2 mt-2">
          <Button variant="outline" onClick={onCancel}>{cancelText || "取消"}</Button>
          <Button variant={danger ? "destructive" : "default"} onClick={onOk}>{okText || "确定"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
