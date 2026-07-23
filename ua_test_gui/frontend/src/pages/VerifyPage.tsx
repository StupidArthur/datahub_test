// 验证页:选 mock + endpoint + 等待 -> 11 类型读写回写遍历 + 结果表。交互不变,样式换 Tailwind + Shadcn。
import { useState, useEffect } from "react";
import { api, mock, verify } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Card, CardContent, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "../components/ui/table";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "../components/ui/select";

export function VerifyPage({ pushToast, localIP }: {
  pushToast: (k: ToastKind, t: string) => void;
  localIP: string;
}) {
  const [mocks, setMocks] = useState<mock.MockSummary[]>([]);
  const [mockKey, setMockKey] = useState("functional");
  const [settle, setSettle] = useState(1.0);
  const [result, setResult] = useState<verify.VerifyRunResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { api.listMocks().then((r) => setMocks(r.mocks || [])).catch(() => {}); }, []);
  const mockSel = mocks.find((m) => m.key === mockKey);
  const endpoint = mockSel && localIP ? `opc.tcp://${localIP}:${mockSel.port}/ua_mocker/` : "";

  async function run() {
    setLoading(true);
    try {
      const res = await api.runVerification({
        mockKey, endpoint, namespaceIndex: 1, settleSec: settle, runId: 0,
      } as verify.VerifyRequest);
      setResult(res);
      pushToast("success", `验证完成: ${res.passed} 通过 / ${res.failed} 失败`);
    } catch (e) { pushToast("error", (e as Error).message); }
    finally { setLoading(false); }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3.5 max-w-2xl">
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-muted-foreground">Mock</label>
          <Select value={mockKey} onValueChange={setMockKey}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              {mocks.map((m) => <SelectItem key={m.key} value={m.key}>{m.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-muted-foreground">endpoint</label>
          <Input value={endpoint} readOnly />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-muted-foreground">写入后等待 RT 生效(秒)</label>
          <Input type="number" step="0.5" value={settle} onChange={(e) => setSettle(+e.target.value)} />
        </div>
        <div className="text-xs text-muted-foreground">遍历 11 个 TPT 支持类型,每类型取 1 个可写位号:读 RT -&gt; 读源端 -&gt; 回写 -&gt; 读回对照。</div>
        <div className="flex items-center gap-3">
          <Button disabled={loading || !endpoint} onClick={run}>{loading ? "验证中..." : "运行验证"}</Button>
        </div>
      </div>
      {result && (
        <Card>
          <CardContent className="p-4 flex flex-col gap-3">
            <CardTitle>结果: {result.passed} 通过 / {result.failed} 失败 / 共 {result.total}</CardTitle>
            <Table>
              <TableHeader><TableRow><TableHead>类型</TableHead><TableHead>位号</TableHead><TableHead>RT 前</TableHead><TableHead>写入值</TableHead><TableHead>RT 后</TableHead><TableHead>结果</TableHead><TableHead>说明</TableHead></TableRow></TableHeader>
              <TableBody>
                {result.results.map((r, i) => (
                  <TableRow key={i}>
                    <TableCell>{r.type}</TableCell><TableCell>{r.tagName}</TableCell>
                    <TableCell>{JSON.stringify(r.rtBefore)}</TableCell><TableCell>{JSON.stringify(r.writeVal)}</TableCell><TableCell>{JSON.stringify(r.rtAfter)}</TableCell>
                    <TableCell>{r.ok ? <Badge variant="success">通过</Badge> : <Badge variant="destructive">失败</Badge>}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{r.msg}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
