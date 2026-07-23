// ua-server-mock 管理页:4 行 table 启停 + 性能参数可编辑保存。交互不变,样式换 Tailwind + Shadcn。
import { useState, useEffect, useRef } from "react";
import { api, mock } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Card, CardContent } from "../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table";
import { EventsOn } from "../../wailsjs/runtime/runtime";

// 后端状态:stopped/starting/ready/failed(本进程)+ running(跨进程探测)。ready/running=运行中。
function isRunning(status: string) {
  return status === "ready" || status === "running" || status === "starting";
}
function statusBadge(status: string) {
  switch (status) {
    case "ready":
    case "running": return <Badge variant="success">运行中</Badge>;
    case "starting": return <Badge variant="warning">启动中</Badge>;
    case "failed": return <Badge variant="destructive">失败</Badge>;
    default: return <Badge variant="secondary">已停止</Badge>;
  }
}

export function MockPage({ pushToast }: { pushToast: (k: ToastKind, t: string) => void }) {
  const [mocks, setMocks] = useState<mock.MockSummary[]>([]);
  const [perf, setPerf] = useState<mock.PerfParams>({ pollN: 10000, writeN: 1000, ratio: 0.9 });
  const [perfEdit, setPerfEdit] = useState<mock.PerfParams>({ pollN: 10000, writeN: 1000, ratio: 0.9 });
  const [busy, setBusy] = useState<string | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const batchTarget = useRef<Set<string>>(new Set());
  const prevStatus = useRef<Record<string, string>>({});

  async function refresh(): Promise<mock.MockSummary[]> {
    try {
      const [listRes, perfRes] = await Promise.all([
        api.listMocks(),
        api.getPerformanceParams(),
      ]);
      const next = listRes.mocks || [];
      setMocks(next);
      const p = perfRes.params;
      const eff = p.pollN || p.writeN || p.ratio ? p : { pollN: 10000, writeN: 1000, ratio: 0.9 };
      setPerf(eff); setPerfEdit(eff);
      return next;
    } catch (e) {
      pushToast("error", (e as Error).message);
      return mocks;
    }
  }

  function checkTransitions(next: mock.MockSummary[]) {
    for (const m of next) {
      const prev = prevStatus.current[m.key];
      if (prev === "starting" && m.status === "ready") {
        pushToast("success", `${m.name} 已启动就绪`);
        if (busy === m.key) setBusy(null);
      } else if (prev === "starting" && m.status === "failed") {
        pushToast("error", `${m.name} 启动失败`);
        if (busy === m.key) setBusy(null);
      }
    }
    prevStatus.current = Object.fromEntries(next.map((m) => [m.key, m.status]));

    // 批量启动过程中,检查目标是否全部完成(starting -> ready/failed)。
    if (batchBusy && batchTarget.current.size > 0) {
      const allDone = Array.from(batchTarget.current).every((key) => {
        const s = next.find((m) => m.key === key)?.status;
        return s !== "starting";
      });
      if (allDone) {
        batchTarget.current.clear();
        setBatchBusy(false);
        pushToast("success", "批量启动完成");
      }
    }
  }

  useEffect(() => {
    refresh().then(checkTransitions);
    // 后端状态变化(mock:state 事件)主动推,前端实时刷新列表并检测 starting->ready/failed。
    const cancel = EventsOn("mock:state", async () => checkTransitions(await refresh()));
    return () => cancel();
  }, []);

  async function start(key: string) {
    const mk = mocks.find((m) => m.key === key);
    if (mk && mk.nodeCount > 500) {
      // 估算对齐实测:分容器优化后 ~0.6ms/节点(11000 节点 ~6s),取 1ms/节点留慢机余量。
      const sec = Math.ceil(mk.nodeCount / 1000);
      pushToast("info", `${mk.name} 共 ${mk.nodeCount} 个位号,启动约需 ${sec} 秒,请耐心等待`);
    }
    setBusy(key);
    try {
      await api.startMock(key);
      pushToast("info", `${mk?.name || key} 启动中,就绪后会自动刷新`);
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
      setBusy(null);
    }
  }
  async function stop(key: string) {
    setBusy(key);
    try {
      await api.stopMock(key);
      pushToast("success", `${key} 已停止`);
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function startAll() {
    const stopped = mocks.filter((m) => m.status === "stopped");
    if (stopped.length === 0) {
      pushToast("info", "没有已停止的 mock 需要启动");
      return;
    }
    batchTarget.current = new Set(stopped.map((m) => m.key));
    setBatchBusy(true);
    try {
      await api.startAllMocks();
      pushToast("info", `已发起批量启动(${stopped.length} 个),将依次就绪`);
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
      batchTarget.current.clear();
      setBatchBusy(false);
    }
  }
  async function stopAll() {
    setBatchBusy(true);
    try {
      await api.stopAllMocks();
      pushToast("success", "已停止全部 mock");
      checkTransitions(await refresh());
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      batchTarget.current.clear();
      setBatchBusy(false);
      setBusy(null);
    }
  }
  async function savePerf() {
    try { await api.setPerformanceParams(perfEdit); setPerf(perfEdit); pushToast("success", "性能参数已保存"); }
    catch (e) { pushToast("error", (e as Error).message); }
  }

  const anyRunning = mocks.some((m) => isRunning(m.status));
  const anyStopped = mocks.some((m) => m.status === "stopped");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        <Button variant="outline" onClick={() => refresh().then(checkTransitions)} disabled={batchBusy}>刷新</Button>
        <Button variant="default" onClick={startAll} disabled={batchBusy || !anyStopped}>
          {batchBusy && batchTarget.current.size > 0 ? "批量启动中..." : "启动全部"}
        </Button>
        <Button variant="destructive" onClick={stopAll} disabled={batchBusy || !anyRunning}>
          {batchBusy && batchTarget.current.size === 0 ? "批量停止中..." : "停止全部"}
        </Button>
      </div>
      <Table>
        <TableHeader><TableRow><TableHead>名称</TableHead><TableHead>端口</TableHead><TableHead>位号数</TableHead><TableHead>状态</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
        <TableBody>
          {mocks.map((m) => (
            <TableRow key={m.key}>
              <TableCell>{m.name}<div className="text-xs text-muted-foreground">{m.key}</div></TableCell>
              <TableCell>{m.port}</TableCell>
              <TableCell>{m.nodeCount}</TableCell>
              <TableCell>{statusBadge(m.status)}</TableCell>
              <TableCell>
                {isRunning(m.status)
                  ? <Button size="sm" variant="destructive" disabled={batchBusy || busy === m.key} onClick={() => stop(m.key)}>{busy === m.key ? "..." : "停止"}</Button>
                  : <Button size="sm" disabled={batchBusy || busy === m.key} onClick={() => start(m.key)}>{busy === m.key ? "启动中" : "启动"}</Button>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Card>
        <CardContent className="p-4 flex flex-col gap-3">
          <div className="font-semibold">性能测试参数(可编辑,启动性能 mock 时生效)</div>
          <div className="flex gap-4 flex-wrap">
            <label className="flex flex-col gap-1.5 text-sm text-muted-foreground flex-1 min-w-40">轮询位号数
              <Input type="number" value={perfEdit.pollN} onChange={(e) => setPerfEdit({ ...perfEdit, pollN: +e.target.value })} /></label>
            <label className="flex flex-col gap-1.5 text-sm text-muted-foreground flex-1 min-w-40">可写位号数
              <Input type="number" value={perfEdit.writeN} onChange={(e) => setPerfEdit({ ...perfEdit, writeN: +e.target.value })} /></label>
            <label className="flex flex-col gap-1.5 text-sm text-muted-foreground flex-1 min-w-40">Double:Bool 配比
              <Input type="number" step="0.1" value={perfEdit.ratio} onChange={(e) => setPerfEdit({ ...perfEdit, ratio: +e.target.value })} /></label>
          </div>
          <div className="text-xs text-muted-foreground">当前生效: 轮询 {perf.pollN} / 可写 {perf.writeN} / 配比 {perf.ratio}</div>
          <Button className="w-fit" onClick={savePerf} disabled={batchBusy}>保存</Button>
        </CardContent>
      </Card>
    </div>
  );
}
