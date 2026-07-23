// TestRunsPage.tsx - 测试任务页。
import { useEffect, useRef, useState } from "react";
import { api, automation } from "../lib/api";
import { RunProgress } from "../components/test/RunProgress";
import { LogViewer } from "../components/test/LogViewer";
import { StatusBadge } from "../components/test/StatusBadge";
import { ToastKind } from "../components/Toast";

export interface TestRunsPageProps {
  pushToast: (kind: ToastKind, text: string) => void;
  selectedIds: string[];
  setSelectedIds: (ids: string[]) => void;
  loggedIn: boolean;
  localIP: string;
}

export function TestRunsPage({ pushToast, selectedIds, setSelectedIds, loggedIn, localIP }: TestRunsPageProps) {
  const [active, setActive] = useState<automation.TestRun | null>(null);
  const [detail, setDetail] = useState<automation.RunDetail | null>(null);
  const [allowPerf, setAllowPerf] = useState(false);
  const [note, setNote] = useState("");
  const pollRef = useRef<any>(null);

  async function refreshActive() {
    try {
      const a = await api.getActiveTestRun();
      setActive(a || null);
      if (a && a.id > 0) {
        const d = await api.getTestRunDetail(a.id);
        setDetail(d);
      } else {
        setDetail(null);
      }
    } catch (e: any) {
      pushToast("error", `获取 active run 失败: ${e?.message || e}`);
    }
  }

  useEffect(() => {
    refreshActive();
    pollRef.current = setInterval(refreshActive, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startRun() {
    if (!loggedIn) {
      pushToast("error", "请先登录被测对象");
      return;
    }
    if (selectedIds.length === 0) {
      pushToast("error", "请先在测试用例页选择用例");
      return;
    }
    try {
      const r = await api.startTestRun({
        selectedCaseIds: selectedIds,
        note,
        allowPerformance: allowPerf,
        runKey: "",
      });
      setActive(r);
      pushToast("success", `已启动 run #${r.id}`);
      refreshActive();
    } catch (e: any) {
      pushToast("error", `启动失败: ${e?.message || e}`);
    }
  }

  async function stopRun() {
    if (!active) return;
    try {
      const r = await api.stopTestRun(active.id);
      setActive(r);
      pushToast("success", `已请求停止 #${active.id}`);
    } catch (e: any) {
      pushToast("error", `停止失败: ${e?.message || e}`);
    }
  }

  async function openDir() {
    if (!active) return;
    try {
      const path = await api.openRunDirectory(active.id);
      pushToast("info", `运行目录: ${path}`);
    } catch (e: any) {
      pushToast("error", `打开目录失败: ${e?.message || e}`);
    }
  }

  function applyPreset(preset: string) {
    if (preset === "smoke") {
      setSelectedIds(["UA-1-1-001", "UA-2-1-001", "UA-3-1-001", "UA-3-2-001", "UA-3-3-001", "UA-3-4-001"]);
    } else if (preset === "ua1") {
      setSelectedIds(["UA-1-1-001", "UA-1-2-001", "UA-1-3-001"]);
    } else if (preset === "ua2") {
      setSelectedIds(["UA-2-1-001", "UA-2-2-001", "UA-2-4-001"]);
    } else if (preset === "ua3") {
      setSelectedIds(["UA-3-1-001", "UA-3-2-001", "UA-3-3-001", "UA-3-4-001", "UA-3-5-001"]);
    }
  }

  const run = active;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 border rounded-md p-4">
        <div className="flex items-center gap-3 mb-3">
          <div className="font-semibold">任务配置</div>
          <div className="text-xs text-muted-foreground">
            登录={loggedIn ? "是" : "否"} · 本机IP={localIP || "(未设置)"} · 已选 {selectedIds.length} 个用例
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <button className="px-3 py-1.5 text-xs rounded-md border hover:bg-accent" onClick={() => applyPreset("smoke")}>冒烟</button>
          <button className="px-3 py-1.5 text-xs rounded-md border hover:bg-accent" onClick={() => applyPreset("ua1")}>UA-1</button>
          <button className="px-3 py-1.5 text-xs rounded-md border hover:bg-accent" onClick={() => applyPreset("ua2")}>UA-2</button>
          <button className="px-3 py-1.5 text-xs rounded-md border hover:bg-accent" onClick={() => applyPreset("ua3")}>UA-3</button>
          <button className="px-3 py-1.5 text-xs rounded-md border hover:bg-accent" onClick={() => setSelectedIds([])}>清空选择</button>
        </div>
        <div className="flex items-center gap-2">
          <input
            className="flex-1 px-3 py-2 rounded-md border bg-background text-sm"
            placeholder="运行备注(可选)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={allowPerf} onChange={(e) => setAllowPerf(e.target.checked)} />
            性能测试已确认(独占环境)
          </label>
          <button
            className="px-3 py-2 rounded-md bg-primary text-primary-foreground text-sm disabled:opacity-50"
            disabled={!!active || selectedIds.length === 0}
            onClick={startRun}
          >
            启动任务
          </button>
          <button
            className="px-3 py-2 rounded-md border text-sm disabled:opacity-50"
            disabled={!active || active.status !== "RUNNING"}
            onClick={stopRun}
          >
            停止
          </button>
        </div>
      </div>

      <div className="col-span-7 border rounded-md p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="font-semibold">Active Run</div>
          {run && (
            <button className="text-xs px-2 py-1 rounded-md border hover:bg-accent" onClick={openDir}>
              打开运行目录
            </button>
          )}
        </div>
        {run ? (
          <RunProgress
            total={run.total}
            progress={run.progress}
            passed={run.passed}
            failed={run.failed}
            errors={run.errors}
            observed={run.observed}
            measured={run.measured}
            cleanupFailed={run.cleanupFailed}
            status={run.status}
            currentCaseId={run.currentCaseId}
            currentStep={run.currentStep}
          />
        ) : (
          <div className="text-sm text-muted-foreground">无活跃 run</div>
        )}
        {run && (
          <div className="mt-4">
            <div className="text-xs text-muted-foreground mb-1">实时日志(runner.log)</div>
            <LogViewer api={api} runId={run.id} refreshMs={2000} />
          </div>
        )}
      </div>

      <div className="col-span-5 border rounded-md p-4">
        <div className="font-semibold mb-2">用例执行列表</div>
        {detail && detail.cases && detail.cases.length > 0 ? (
          <ul className="divide-y text-sm max-h-96 overflow-auto">
            {detail.cases.map((cr) => (
              <li key={cr.id} className="py-2 flex items-center gap-2">
                <StatusBadge status={cr.status} />
                <div className="flex-1">
                  <div className="font-mono text-xs">{cr.caseId}</div>
                  <div className="text-xs text-muted-foreground">{cr.title}</div>
                </div>
                <span className="text-xs text-muted-foreground">{cr.durationMs}ms</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-sm text-muted-foreground">暂无</div>
        )}
      </div>
    </div>
  );
}