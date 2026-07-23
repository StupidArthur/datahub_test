// 操作系统环境检测页:端口表 + 一键杀(二次确认)+ 连通性 + 本地 IP select。
// ua_mocker 运行环境已内嵌:最终产品随包携带 ua_mocker.exe,自动探测,无需用户配置 python/mock 目录。
import { useState, useEffect } from "react";
import { api, env } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Confirm } from "../components/Confirm";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import { Card, CardContent } from "../components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

export function EnvPage({ pushToast, localIP, setLocalIP }: {
  pushToast: (k: ToastKind, t: string) => void;
  localIP: string;
  setLocalIP: (ip: string) => void;
}) {
  const [envStatus, setEnvStatus] = useState<env.EnvStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [killAll, setKillAll] = useState(false);
  const [killPortTarget, setKillPortTarget] = useState<number | null>(null);
  const [mockerExe, setMockerExe] = useState("");
  const [exeOk, setExeOk] = useState(false);

  async function refresh() {
    setLoading(true);
    try { setEnvStatus(await api.getEnvStatus()); }
    catch (e) { pushToast("error", (e as Error).message); }
    finally { setLoading(false); }
  }
  async function loadMockerEnv() {
    try {
      const r = await api.getMockerConfig();
      setMockerExe(r.exe);
      setExeOk(r.exeOk);
    } catch (e) { pushToast("error", (e as Error).message); }
  }
  useEffect(() => { refresh(); loadMockerEnv(); }, []);

  async function doKill(port: number) {
    try { await api.killPort(port); pushToast("success", `端口 ${port} 已清理`); refresh(); }
    catch (e) { pushToast("error", (e as Error).message); }
    setKillPortTarget(null);
  }
  async function doKillAll() {
    const used = envStatus?.ports.filter((p) => p.inUse) || [];
    for (const p of used) {
      try { await api.killPort(p.port); } catch { /* 杀不掉的让用户自行处理 */ }
    }
    setKillAll(false); refresh(); pushToast("success", "已一键清理占用端口");
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2">
        <Button variant="outline" onClick={refresh} disabled={loading}>{loading ? "刷新中..." : "刷新"}</Button>
        <Button variant="destructive" onClick={() => setKillAll(true)}
          disabled={!envStatus?.ports.some((p) => p.inUse)}>一键清理占用端口</Button>
      </div>

      <Card>
        <CardContent className="p-4 flex flex-col gap-3">
          <div className="font-semibold flex items-center gap-2">
            ua_mocker 运行环境
            {exeOk
              ? <Badge variant="success">已就绪</Badge>
              : <Badge variant="destructive">未就绪</Badge>}
          </div>
          <div className="text-sm text-muted-foreground">
            最终产品已内置 ua_mocker.exe，程序会自动探测，无需手动配置 python 或 mock 目录。
          </div>
          <div className="text-sm">
            <span className="text-muted-foreground">当前 exe: </span>
            <span className="font-medium">{mockerExe || "(自动探测中...)"}</span>
            {exeOk ? " ✓" : " ✗ 找不到"}
          </div>
          {!exeOk && (
            <div className="text-xs text-destructive bg-destructive/10 p-2 rounded">
              未找到 ua_mocker.exe。请确保它与 ua_test_gui.exe 放在同一目录，或放在其上溯目录中。
            </div>
          )}
        </CardContent>
      </Card>

      <Table>
        <TableHeader><TableRow><TableHead>端口</TableHead><TableHead>状态</TableHead><TableHead>PID</TableHead><TableHead>进程</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
        <TableBody>
          {envStatus?.ports.map((p) => (
            <TableRow key={p.port}>
              <TableCell>{p.port}</TableCell>
              <TableCell>{p.inUse ? <Badge variant="destructive">占用</Badge> : <Badge variant="success">空闲</Badge>}</TableCell>
              <TableCell>{p.inUse ? p.pid : "-"}</TableCell>
              <TableCell>{p.process || "-"}</TableCell>
              <TableCell>{p.inUse && <Button size="sm" variant="destructive" onClick={() => setKillPortTarget(p.port)}>杀进程</Button>}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-muted-foreground">本地 IP(TPT 加数据源时用此地址连 mock)</label>
        <Select value={localIP} onValueChange={(v) => { setLocalIP(v); localStorage.setItem("local_ip", v); }}>
          <SelectTrigger><SelectValue placeholder="(请选择)" /></SelectTrigger>
          <SelectContent>
            {envStatus?.localIps.map((ip) => <SelectItem key={ip} value={ip}>{ip}</SelectItem>)}
          </SelectContent>
        </Select>
        {envStatus?.pickIp && <span className="text-xs text-muted-foreground">推荐: {envStatus.pickIp}</span>}
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-muted-foreground">被测对象连通性(通过能否登录判断)</label>
        <span>{envStatus?.connectivityOk
          ? <Badge variant="success">{envStatus.connectivityMsg}</Badge>
          : <Badge variant="destructive">未登录/不通</Badge>}</span>
      </div>

      <Confirm open={killAll} title="一键清理占用端口" danger okText="清理" onOk={doKillAll} onCancel={() => setKillAll(false)}>
        将杀掉所有 18960-18969 占用端口的进程。杀不掉的需你自行处理。继续?
      </Confirm>
      <Confirm open={killPortTarget !== null} title="杀进程" danger okText="杀"
        onOk={() => killPortTarget !== null && doKill(killPortTarget)} onCancel={() => setKillPortTarget(null)}>
        确认杀掉端口 {killPortTarget} 的进程?
      </Confirm>
    </div>
  );
}
