// StatusBadge.tsx - 测试状态徽章(PASS/FAIL/...).
import { Badge } from "../ui/badge";

const COLORS: Record<string, string> = {
  PASS: "bg-success/20 text-success",
  FAIL: "bg-destructive/20 text-destructive",
  ERROR: "bg-destructive/30 text-destructive",
  RUNNING: "bg-primary/20 text-primary",
  PENDING: "bg-muted text-muted-foreground",
  SKIP: "bg-muted text-muted-foreground",
  BLOCKED: "bg-warning/20 text-warning",
  OBSERVED: "bg-info/20 text-info",
  MEASURED: "bg-info/20 text-info",
  CANCELLED: "bg-muted text-muted-foreground",
  CLEANUP_FAILED: "bg-destructive/20 text-destructive",
  FINISHED: "bg-success/20 text-success",
  INTERRUPTED: "bg-warning/20 text-warning",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? "bg-muted text-muted-foreground";
  return <Badge className={cls}>{status || "—"}</Badge>;
}