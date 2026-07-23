// CaseResultDetail.tsx - 单用例详情(步骤 / evidence / 指标)。
import { automation } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";

export function CaseResultDetail({ cr }: { cr: automation.CaseResult }) {
  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="flex items-center gap-2">
        <span className="font-mono">{cr.caseId}</span>
        <span className="text-muted-foreground">{cr.title}</span>
        <StatusBadge status={cr.status} />
        <span className="text-xs text-muted-foreground">{cr.durationMs}ms</span>
      </div>
      {cr.summary && <div className="text-xs text-muted-foreground">{cr.summary}</div>}
      {cr.cleanupStatus && (
        <div className="text-xs">
          cleanup: <StatusBadge status={cr.cleanupStatus} />
          {cr.cleanupMessage ? <span className="ml-2 text-muted-foreground">{cr.cleanupMessage}</span> : null}
        </div>
      )}
    </div>
  );
}