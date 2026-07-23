// RunProgress.tsx - 进度条 + 计数。
import { Progress } from "../ui/progress";
import { StatusBadge } from "./StatusBadge";

export interface RunProgressProps {
  total: number;
  progress: number;
  passed: number;
  failed: number;
  errors: number;
  observed: number;
  measured: number;
  cleanupFailed: number;
  status: string;
  currentCaseId?: string;
  currentStep?: string;
}

export function RunProgress(props: RunProgressProps) {
  const pct = props.total > 0 ? Math.round((props.progress / props.total) * 100) : 0;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusBadge status={props.status} />
          <span className="text-sm text-muted-foreground">{props.progress}/{props.total}</span>
        </div>
        <div className="text-sm text-muted-foreground">{pct}%</div>
      </div>
      <Progress value={pct} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <div>PASS: <span className="font-semibold">{props.passed}</span></div>
        <div>FAIL: <span className="font-semibold">{props.failed}</span></div>
        <div>ERROR: <span className="font-semibold">{props.errors}</span></div>
        <div>OBSERVED: <span className="font-semibold">{props.observed}</span></div>
        <div>MEASURED: <span className="font-semibold">{props.measured}</span></div>
        <div>CLEANUP_FAILED: <span className="font-semibold">{props.cleanupFailed}</span></div>
      </div>
      {(props.currentCaseId || props.currentStep) && (
        <div className="text-xs text-muted-foreground">
          当前: {props.currentCaseId || "—"} {props.currentStep ? `· ${props.currentStep}` : ""}
        </div>
      )}
    </div>
  );
}