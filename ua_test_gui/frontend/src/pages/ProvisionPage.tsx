// 数据源组态页:顶部 Tabs 选 mock + 数据源状态 + 位号管理 + 位号明细弹窗。
import { useEffect, useMemo, useState } from "react";
import { api, mock as mockNs, provision } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Confirm } from "../components/Confirm";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import {
  Dialog, DialogContent, DialogTitle,
} from "../components/ui/dialog";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "../components/ui/table";

export function ProvisionPage({ pushToast, localIP }: {
  pushToast: (k: ToastKind, t: string) => void;
  localIP: string;
}) {
  const [mocks, setMocks] = useState<mockNs.MockSummary[]>([]);
  const [mockKey, setMockKey] = useState("functional");
  const [state, setState] = useState<provision.ProvisionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [hbValue, setHbValue] = useState<provision.HeartbeatValue | null>(null);
  const [hbPolling, setHbPolling] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailSearch, setDetailSearch] = useState("");

  // 二次确认弹窗
  const [confirmAddDs, setConfirmAddDs] = useState(false);
  const [confirmDelDs, setConfirmDelDs] = useState(false);
  const [confirmAddTags, setConfirmAddTags] = useState(false);
  const [confirmDelTags, setConfirmDelTags] = useState(false);

  // 加载 mock 列表
  useEffect(() => { api.listMocks().then((r) => setMocks(r.mocks || [])).catch(() => {}); }, []);

  const mockSel = mocks.find((m) => m.key === mockKey);
  const endpoint = useMemo(() => {
    return mockSel && localIP ? `opc.tcp://${localIP}:${mockSel.port}/ua_mocker/` : "";
  }, [mockSel, localIP]);
  const dsName = useMemo(() => `ua_test_gui_${mockKey}`, [mockKey]);
  const heartbeatTag = state?.heartbeatTag || "";

  // 加载 provision state
  const loadState = async (silent = false) => {
    if (!endpoint || !mockSel) return;
    if (!silent) setLoading(true);
    setError(null);
    try {
      const s = await api.getProvisionState({
        mockKey, endpoint, frequency: 10,
      } as provision.ProvisionStateRequest);
      setState(s);
    } catch (e) {
      const msg = (e as Error).message || String(e);
      setError(msg);
      if (!silent) pushToast("error", msg);
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    setState(null);
    setHbValue(null);
    setHbPolling(false);
    loadState();
    if (!autoRefresh) return;
    const id = setInterval(() => loadState(true), 5000);
    return () => clearInterval(id);
  }, [mockKey, endpoint, autoRefresh]);

  // 心跳轮询
  useEffect(() => {
    if (!hbPolling || !state?.dsInfo || !heartbeatTag) {
      setHbValue(null);
      return;
    }
    const poll = async () => {
      try {
        const v = await api.getHeartbeatValue({
          dsId: state.dsInfo!.id, tagName: heartbeatTag,
        } as provision.GetHeartbeatValueRequest);
        setHbValue(v);
      } catch (e) {
        setHbValue({ tagName: heartbeatTag, ok: false, msg: (e as Error).message } as provision.HeartbeatValue);
      }
    };
    poll();
    const id = setInterval(poll, 1000);
    return () => clearInterval(id);
  }, [hbPolling, state?.dsInfo?.id, heartbeatTag]);

  async function doAction<T>(action: () => Promise<T>, okMsg: string) {
    setBusy(true);
    try {
      await action();
      pushToast("success", okMsg);
      await loadState(true);
    } catch (e) {
      pushToast("error", (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // 数据源操作
  async function addDataSource() {
    await doAction(
      () => api.addDataSource({ dsName, endpoint } as provision.AddDataSourceRequest),
      "数据源创建成功",
    );
    setConfirmAddDs(false);
  }

  async function deleteDataSource() {
    if (!state?.dsInfo) return;
    await doAction(
      () => api.deleteDataSource({ dsId: state.dsInfo!.id } as provision.DeleteDataSourceRequest),
      "数据源删除成功",
    );
    setConfirmDelDs(false);
  }

  async function toggleDsState() {
    if (!state?.dsInfo) return;
    const enabled = !state.dsInfo.dsStatus;
    await doAction(
      () => api.changeDsState({ dsId: state.dsInfo!.id, enabled } as provision.ChangeDsStateRequest),
      enabled ? "数据源已启用" : "数据源已禁用",
    );
  }

  // 位号操作
  async function addMissingTags() {
    await doAction(
      () => api.addMissingTags({ mockKey, endpoint, frequency: 10 } as provision.AddMissingTagsRequest),
      "差量添加完成",
    );
    setConfirmAddTags(false);
  }

  async function deleteAllTags() {
    if (!state?.dsInfo) return;
    await doAction(
      () => api.deleteAllTags({ dsId: state.dsInfo!.id } as provision.DeleteAllTagsRequest),
      "所有位号已删除",
    );
    setConfirmDelTags(false);
  }

  // 位号明细过滤
  const detailTags = useMemo(() => {
    if (!state) return [];
    const tags = state.tagStatuses || [];
    if (!detailSearch.trim()) return tags;
    const s = detailSearch.trim().toLowerCase();
    return tags.filter((t) => t.name.toLowerCase().includes(s));
  }, [state, detailSearch]);

  const dsExists = !!state?.dsInfo;
  const dsTagCount = state?.tagsInDsCount || 0;
  const mockTagCount = (state?.mockTags || []).length;

  return (
    <div className="flex flex-col gap-4">
      {/* 顶部 Mock Tabs */}
      <div className="flex flex-wrap gap-2 border-b pb-2">
        {mocks.map((m) => (
          <button
            key={m.key}
            onClick={() => setMockKey(m.key)}
            disabled={busy}
            className={[
              "px-4 py-2 text-sm font-medium rounded-t-md transition-colors",
              mockKey === m.key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            ].join(" ")}
          >
            {m.name} ({m.port})
          </button>
        ))}
      </div>

      {!localIP && (
        <div className="text-sm text-destructive">先在"操作系统环境检测"页选择本地 IP</div>
      )}

      {error && (
        <div className="p-3 bg-destructive/10 border border-destructive/30 rounded-md text-sm text-destructive">
          加载失败: {error}
        </div>
      )}

      {state && (
        <>
          {/* 卡片 1: 数据源状态 */}
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">数据源状态</CardTitle>
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                    <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
                    自动刷新
                  </label>
                  <Button size="sm" variant="outline" onClick={() => loadState()} disabled={busy || loading}>
                    {loading ? "刷新中..." : "刷新"}
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">名称</span>
                  <span className="font-medium">{state.dsInfo?.dsName || dsName}</span>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">数据源地址</span>
                  <code className="text-xs">{endpoint || "-"}</code>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">是否启用</span>
                  <div className="flex items-center gap-2">
                    <Badge variant={state.dsInfo ? (state.dsInfo.dsStatus ? "default" : "secondary") : "outline"}>
                      {state.dsInfo ? (state.dsInfo.dsStatus ? "启用" : "禁用") : "-"}
                    </Badge>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={toggleDsState}
                      disabled={busy || !dsExists}
                    >
                      {state.dsInfo?.dsStatus ? "禁用" : "启用"}
                    </Button>
                  </div>
                </div>

                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">数据源是否存在</span>
                  <Badge variant={dsExists ? "default" : "outline"}>{dsExists ? "存在" : "不存在"}</Badge>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">操作</span>
                  <div className="flex items-center gap-2">
                    {dsExists ? (
                      <Button size="sm" variant="destructive" onClick={() => setConfirmDelDs(true)} disabled={busy}>
                        删除数据源
                      </Button>
                    ) : (
                      <Button size="sm" onClick={() => setConfirmAddDs(true)} disabled={busy || !endpoint}>
                        添加数据源
                      </Button>
                    )}
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <span className="text-muted-foreground text-xs">在线与否</span>
                  <div className="flex items-center gap-2">
                    <Badge variant={state.dsAlive ? "default" : "secondary"}>
                      {dsExists ? (state.dsAlive ? "在线" : "离线") : "-"}
                    </Badge>
                    {dsExists && <span className="text-xs text-muted-foreground">(TPT 心跳约 40~60s 延迟)</span>}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* 卡片 2: 位号管理 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">位号管理</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* 数据源位号数 = mock 上的位号数 */}
                <div className="flex flex-col gap-2 p-3 border rounded-md">
                  <div className="flex items-center justify-between">
                    <div className="flex flex-col">
                      <span className="text-xs text-muted-foreground">数据源位号数（mock 位号数）</span>
                      <span className="text-2xl font-bold">{mockTagCount}</span>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setConfirmAddTags(true)}
                      disabled={busy || !dsExists || (state.missingTags || []).length === 0}
                    >
                      差量添加
                    </Button>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    mock 方案定义的位号总数
                  </div>
                </div>

                {/* DataHub 组态位号数 = TPT 上的位号数 */}
                <div className="flex flex-col gap-2 p-3 border rounded-md">
                  <div className="flex items-center justify-between">
                    <div className="flex flex-col">
                      <span className="text-xs text-muted-foreground">DataHub 组态位号数</span>
                      <span className="text-2xl font-bold">{dsTagCount}</span>
                    </div>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => setConfirmDelTags(true)}
                      disabled={busy || !dsExists || dsTagCount === 0}
                    >
                      删除所有
                    </Button>
                  </div>
                  <div className="text-xs text-muted-foreground">
                    TPT DataHub 上该数据源下实际位号数
                  </div>
                </div>
              </div>

              {/* 心跳验证 */}
              <div className="mt-4 flex flex-col gap-2 p-3 border rounded-md">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col">
                    <span className="text-xs text-muted-foreground">心跳验证</span>
                    <span className="font-mono text-sm">
                      {hbValue?.ok ? String(hbValue.tagValue) : (hbValue?.msg || "未启动")}
                    </span>
                  </div>
                  <Button
                    size="sm"
                    variant={hbPolling ? "secondary" : "outline"}
                    onClick={() => setHbPolling((v) => !v)}
                    disabled={busy || !dsExists}
                  >
                    {hbPolling ? "停止" : "开始验证"}
                  </Button>
                </div>
                {hbValue?.ok && (
                  <div className="text-xs text-muted-foreground">
                    tag={hbValue.tagName} quality={hbValue.quality}
                  </div>
                )}
              </div>

              {/* 位号明细 */}
              <div className="mt-4">
                <Button size="sm" variant="outline" onClick={() => setDetailOpen(true)} disabled={!dsExists}>
                  位号明细
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {/* 二次确认弹窗 */}
      <Confirm open={confirmAddDs} title="添加数据源" okText="确认添加" onOk={addDataSource} onCancel={() => setConfirmAddDs(false)}>
        将创建空数据源 <b>{dsName}</b>，endpoint: <code>{endpoint}</code>
      </Confirm>

      <Confirm open={confirmDelDs} title="删除数据源" danger okText="确认删除" onOk={deleteDataSource} onCancel={() => setConfirmDelDs(false)}>
        将删除数据源 <b>{state?.dsInfo?.dsName}</b> 及其下所有位号，继续？
      </Confirm>

      <Confirm open={confirmAddTags} title="差量添加位号" okText="确认添加" onOk={addMissingTags} onCancel={() => setConfirmAddTags(false)}>
        将向数据源添加 {(state?.missingTags || []).length} 个缺失位号，继续？
      </Confirm>

      <Confirm open={confirmDelTags} title="删除所有位号" danger okText="确认删除" onOk={deleteAllTags} onCancel={() => setConfirmDelTags(false)}>
        将删除数据源下所有 {dsTagCount} 个位号，继续？
      </Confirm>

      {/* 位号明细弹窗 */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] flex flex-col">
          <div className="flex items-center justify-between">
            <DialogTitle>位号明细 ({detailTags.length})</DialogTitle>
            <Input
              placeholder="搜索位号名"
              value={detailSearch}
              onChange={(e) => setDetailSearch(e.target.value)}
              className="max-w-xs h-8 text-sm"
            />
          </div>
          <div className="flex-1 overflow-auto border rounded-md mt-2">
            <Table>
              <TableHeader className="sticky top-0 bg-background">
                <TableRow>
                  <TableHead className="w-16">#index</TableHead>
                  <TableHead>位号名</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>可写</TableHead>
                  <TableHead>状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detailTags.map((t, idx) => (
                  <TableRow key={t.name}>
                    <TableCell className="text-muted-foreground">{idx + 1}</TableCell>
                    <TableCell className="font-mono text-xs">{t.name}</TableCell>
                    <TableCell>{t.mockerType}</TableCell>
                    <TableCell>{t.writable ? "是" : "否"}</TableCell>
                    <TableCell>
                      {t.inDs ? (
                        t.duplicate ? (
                          <Badge variant="destructive">重复 x{t.duplicateCount}</Badge>
                        ) : (
                          <Badge variant="default">已存在</Badge>
                        )
                      ) : (
                        <Badge variant="warning">缺失</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {detailTags.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">无数据</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
