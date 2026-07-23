// lib/api.ts - 后端能力封装:调用 wailsjs 6 个业务 binding。
//
// 错误模型:Go 端 (T, error),wails 运行时把 error reject 成 Promise 失败,前端直接 try/catch。
// (旧版把 error 放结果 struct 字段 + unwrap 提取;新版移除 Error 字段,无需 unwrap。)
//
// listMocks/getPerformanceParams/listRuns:Go 端返回直接类型([]MockSummary/PerfParams/[]RunRecord),
// 这里包成 {mocks}/{params}/{runs} 保持前端访问结构不变(UI 交互不动)。
import { Login } from "../../wailsjs/go/bindings/SubjectBinding";
import { GetEnvStatus, KillPort, GetMockerConfig, SetMockerConfig } from "../../wailsjs/go/bindings/EnvBinding";
import { ListMocks, StartMock, StopMock, StopAllMocks, StartAllMocks, GetPerformanceParams, SetPerformanceParams } from "../../wailsjs/go/bindings/MockBinding";
import { Provision, GetProvisionState, AddMissingTags, DeleteDuplicateTags, RebuildDataSource, AddDataSource, DeleteDataSource, ChangeDsState, DeleteAllTags, GetHeartbeatValue } from "../../wailsjs/go/bindings/ProvisionBinding";
import { RunVerification } from "../../wailsjs/go/bindings/VerifyBinding";
import { ListRuns, GetRunDetail } from "../../wailsjs/go/bindings/HistoryBinding";
import {
  ListTestCases,
  RefreshTestCatalog,
  StartTestRun,
  StopTestRun,
  GetActiveTestRun,
  ListTestRuns,
  GetTestRunDetail,
  GetRunEvents,
  ReadRunLog,
  OpenRunDirectory,
} from "../../wailsjs/go/bindings/AutomationBinding";
import { automation, bindings, env, mock, provision, verify } from "../../wailsjs/go/models";

// re-export wails 生成的 DTO 命名空间,供页面按业务域引用类型(替代旧 main 命名空间)。
export { automation, bindings, env, mock, provision, verify };

export const api = {
  login: (req: bindings.LoginRequest) => Login(req),
  getEnvStatus: () => GetEnvStatus(),
  // ListMocks 返回 MockSummary[];包成 {mocks} 保持前端 (await api.listMocks()).mocks 不变。
  listMocks: () => ListMocks().then((mocks) => ({ mocks })),
  startMock: (key: string) => StartMock(key),
  stopMock: (key: string) => StopMock(key),
  stopAllMocks: () => StopAllMocks(),
  startAllMocks: () => StartAllMocks(),
  provision: (req: provision.ProvisionRequest) => Provision(req),
  getProvisionState: (req: provision.ProvisionStateRequest) => GetProvisionState(req),
  addMissingTags: (req: provision.AddMissingTagsRequest) => AddMissingTags(req),
  deleteDuplicateTags: (req: provision.DeleteDuplicateTagsRequest) => DeleteDuplicateTags(req),
  rebuildDataSource: (req: provision.RebuildDataSourceRequest) => RebuildDataSource(req),
  addDataSource: (req: provision.AddDataSourceRequest) => AddDataSource(req),
  deleteDataSource: (req: provision.DeleteDataSourceRequest) => DeleteDataSource(req),
  changeDsState: (req: provision.ChangeDsStateRequest) => ChangeDsState(req),
  deleteAllTags: (req: provision.DeleteAllTagsRequest) => DeleteAllTags(req),
  getHeartbeatValue: (req: provision.GetHeartbeatValueRequest) => GetHeartbeatValue(req),
  runVerification: (req: verify.VerifyRequest) => RunVerification(req),
  // ListRuns 返回 RunRecord[];包成 {runs}。
  listRuns: () => ListRuns().then((runs) => ({ runs })),
  getRunDetail: (runId: number) => GetRunDetail(runId),
  killPort: (port: number) => KillPort(port),
  setPerformanceParams: (p: mock.PerfParams) => SetPerformanceParams(p),
  // GetPerformanceParams 返回 PerfParams;包成 {params}。
  getPerformanceParams: () => GetPerformanceParams().then((params) => ({ params })),
  getMockerConfig: () => GetMockerConfig(),
  setMockerConfig: (req: bindings.SetMockerConfigRequest) => SetMockerConfig(req),

  // automation -----------------------------------------------------------
  listTestCases: () => ListTestCases(),
  refreshTestCatalog: () => RefreshTestCatalog(),
  startTestRun: (req: automation.StartRunRequest) => StartTestRun(req),
  stopTestRun: (runId: number) => StopTestRun(runId),
  getActiveTestRun: () => GetActiveTestRun(),
  listTestRuns: (req: automation.ListRunsRequest) => ListTestRuns(req).then((runs) => ({ runs })),
  getTestRunDetail: (runId: number) => GetTestRunDetail(runId),
  getRunEvents: (req: automation.GetEventsRequest) => GetRunEvents(req),
  readRunLog: (req: automation.ReadLogRequest) => ReadRunLog(req),
  openRunDirectory: (runId: number) => OpenRunDirectory(runId),
};

// 前端实时解析 URL(对齐后端 ParseSubjectURL):协议 + host:port + 租户。
// 用户输入到哪一级都截出有效 base_url。
export function parseSubjectURL(raw: string): { protocol: string; baseUrl: string; tenantId: string } {
  const s = raw.trim();
  if (!/^https?:\/\//i.test(s)) return { protocol: "", baseUrl: "", tenantId: "" };
  try {
    const u = new URL(s);
    const protocol = u.protocol.replace(":", "").toLowerCase();
    const baseUrl = `${protocol}://${u.host}`;
    let tenantId = u.searchParams.get("tenantId") || u.searchParams.get("tenant_id") || u.searchParams.get("tenant") || "";
    if (!tenantId) {
      const parts = u.pathname.replace(/^\/+|\/+$/g, "").split("/");
      for (let i = 0; i < parts.length; i++) {
        if (parts[i] === "tenant" && i + 1 < parts.length) { tenantId = parts[i + 1]; break; }
      }
    }
    return { protocol, baseUrl, tenantId };
  } catch {
    return { protocol: "", baseUrl: "", tenantId: "" };
  }
}
