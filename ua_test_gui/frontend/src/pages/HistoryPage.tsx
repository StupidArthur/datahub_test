// HistoryPage.tsx - 通用任务历史(自动化 runs)。
import { useState, useEffect } from "react";
import { api, automation } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardTitle } from "../components/ui/card";
import { StatusBadge } from "../components/test/StatusBadge";
import { CaseResultDetail } from "../components/test/CaseResultDetail";
import { MetricTable } from "../components/test/MetricTable";
import { LogViewer } from "../components/test/LogViewer";

export function HistoryPage({ pushToast }: { pushToast: (k: ToastKind, t: string) => void }) {
  const [runs, setRuns] = useState<automation.TestRun[]>([]);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [detail, setDetail] = useState<automation.RunDetail | null>(null);

  async function refresh() {
    try {
      const { runs: rs } = await api.listTestRuns({ limit: 100, status: statusFilter, keyword });
      setRuns(rs || []);
    } catch (e) {
      pushToast("error", (e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openRun(id: number) {
    try {
      setDetail(await api.getTestRunDetail(id));
    } catch (e) {
      pushToast("error", (e as Error).message);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2 items-center">
        <input
          className="px-3 py-2 rounded-md border bg-background text-sm w-60"
          placeholder="关键字(runKey / note)"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <select
          className="px-3 py-2 rounded-md border bg-background text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">全部状态</option>
          <option value="RUNNING">RUNNING</option>
          <option value="FINISHED">FINISHED</option>
          <option value="FAILED">FAILED</option>
          <option value="CANCELLED">CANCELLED</option>
          <option value="INTERRUPTED">INTERRUPTED</option>
        </select>
        <Button variant="outline" onClick={refresh}>刷新</Button>
      </div>

      <div className="border rounded-md overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="text-left p-2">ID</th>
              <th className="text-left p-2">状态</th>
              <th className="text-left p-2">用例</th>
              <th className="text-left p-2">P/F/E</th>
              <th className="text-left p-2">进度</th>
              <th className="text-left p-2">开始</th>
              <th className="text-left p-2">结束</th>
              <th className="text-left p-2">note</th>
              <th className="text-left p-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="border-t">
                <td className="p-2 font-mono">{r.id}</td>
                <td className="p-2"><StatusBadge status={r.status} /></td>
                <td className="p-2">{r.total}</td>
                <td className="p-2">{r.passed}/{r.failed}/{r.errors}</td>
                <td className="p-2">{r.progress}/{r.total}</td>
                <td className="p-2 text-xs text-muted-foreground">{r.startedAt}</td>
                <td className="p-2 text-xs text-muted-foreground">{r.finishedAt}</td>
                <td className="p-2 text-xs">{r.note}</td>
                <td className="p-2"><Button size="sm" variant="outline" onClick={() => openRun(r.id)}>详情</Button></td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr><td colSpan={9} className="p-4 text-center text-muted-foreground">暂无历史</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {detail && (
        <Card>
          <CardContent className="p-4 flex flex-col gap-4">
            <CardTitle>Run #{detail.run.id} · {detail.run.status}</CardTitle>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>通过 <span className="font-semibold">{detail.run.passed}</span></div>
              <div>失败 <span className="font-semibold">{detail.run.failed}</span></div>
              <div>错误 <span className="font-semibold">{detail.run.errors}</span></div>
              <div>OBS/MEA <span className="font-semibold">{detail.run.observed}/{detail.run.measured}</span></div>
              <div>CLEANUP <span className="font-semibold">{detail.run.cleanupFailed}</span></div>
              <div>PID <span className="font-mono">{detail.run.pid}</span></div>
              <div>目录 <span className="font-mono text-xs">{detail.run.runDir}</span></div>
              <div>note <span className="text-xs">{detail.run.note}</span></div>
            </div>

            <div>
              <div className="text-xs font-medium mb-1">用例结果</div>
              <ul className="divide-y text-sm max-h-72 overflow-auto border rounded">
                {detail.cases.map((cr) => (
                  <li key={cr.id} className="px-3 py-2">
                    <CaseResultDetail cr={cr} />
                  </li>
                ))}
                {detail.cases.length === 0 && (
                  <li className="px-3 py-2 text-muted-foreground">暂无</li>
                )}
              </ul>
            </div>

            <div>
              <div className="text-xs font-medium mb-1">指标</div>
              <MetricTable metrics={detail.metrics} />
            </div>

            <div>
              <div className="text-xs font-medium mb-1">evidence</div>
              <ul className="text-xs space-y-1">
                {detail.evidence.map((e) => (
                  <li key={e.id} className="font-mono">{e.kind} · {e.caseId} · {e.path} {e.title ? `· ${e.title}` : ""}</li>
                ))}
                {detail.evidence.length === 0 && <li className="text-muted-foreground">暂无</li>}
              </ul>
            </div>

            <div>
              <div className="text-xs font-medium mb-1">runner.log</div>
              <LogViewer api={api} runId={detail.run.id} refreshMs={3000} />
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}