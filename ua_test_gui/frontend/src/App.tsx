// App.tsx - 主壳:左侧分组导航 + 右侧单页内容(Notion 风格 Tailwind)。
// 导航分组(用户 plan 模式设计):环境管理 / 自动化测试 / 辅助工具。
// 共享状态:toast 反馈、登录态、本地 IP、跨页选择的 caseIds。
import { useState, useCallback } from "react";
import { useToast } from "./components/ui/use-toast";
import { Toaster, ToastKind } from "./components/Toast";
import { SubjectPage } from "./pages/SubjectPage";
import { EnvPage } from "./pages/EnvPage";
import { MockPage } from "./pages/MockPage";
import { ProvisionPage } from "./pages/ProvisionPage";
import { VerifyPage } from "./pages/VerifyPage";
import { HistoryPage } from "./pages/HistoryPage";
import { TestCasesPage } from "./pages/TestCasesPage";
import { TestRunsPage } from "./pages/TestRunsPage";
import { ErrorBoundary } from "./components/ErrorBoundary";

type Page =
  | "subject"
  | "env"
  | "mock"
  | "provision"
  | "verify"
  | "history"
  | "cases"
  | "runs";

const NAV: { group: string; items: { key: Page; label: string }[] }[] = [
  { group: "环境管理", items: [
    { key: "subject", label: "被测对象" },
    { key: "env", label: "操作系统环境检测" },
    { key: "mock", label: "ua-server-mock 管理" },
  ] },
  { group: "自动化测试", items: [
    { key: "cases", label: "测试用例" },
    { key: "runs", label: "测试任务" },
    { key: "history", label: "运行历史" },
  ] },
  { group: "辅助工具", items: [
    { key: "provision", label: "数据源组态" },
    { key: "verify", label: "旧验证" },
  ] },
];

function App() {
  const [page, setPage] = useState<Page>("subject");
  const [loggedIn, setLoggedIn] = useState(false);
  const [localIP, setLocalIP] = useState(localStorage.getItem("local_ip") || "");
  const [selectedCaseIds, setSelectedCaseIds] = useState<string[]>([]);
  const { toasts, push, dismiss } = useToast();

  const pushToast = useCallback((kind: ToastKind, text: string) => {
    push(kind, text);
  }, [push]);

  const allItems = NAV.flatMap((g) => g.items);

  return (
    <div className="flex h-screen w-screen bg-background text-foreground">
      <aside className="w-56 flex-shrink-0 border-r bg-muted/30 flex flex-col">
        <div className="px-5 py-5 text-base font-semibold text-primary">UA 测试工具</div>
        <nav className="flex flex-col px-2 gap-1 overflow-y-auto">
          {NAV.map((g) => (
            <div key={g.group} className="flex flex-col">
              <div className="text-[11px] text-muted-foreground px-3 pt-3 pb-1 uppercase tracking-wide">{g.group}</div>
              {g.items.map((it) => (
                <button
                  key={it.key}
                  className={"text-left text-sm px-3 py-2 rounded-md transition-colors " +
                    (page === it.key ? "bg-primary text-primary-foreground" : "hover:bg-accent hover:text-accent-foreground")}
                  onClick={() => setPage(it.key)}
                >
                  {it.label}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-13 flex-shrink-0 flex items-center justify-between px-6 py-3 border-b font-semibold">
          <span>{allItems.find((i) => i.key === page)?.label}</span>
          <span className={"text-xs px-2.5 py-1 rounded-full " + (loggedIn ? "bg-success/10 text-success" : "bg-muted text-muted-foreground")}>
            {loggedIn ? "已登录" : "未登录"}
          </span>
        </header>
        <section className="flex-1 overflow-auto p-6">
          <div className="w-full">
            {page === "subject" && <SubjectPage pushToast={pushToast} onLoggedIn={() => setLoggedIn(true)} />}
            {page === "env" && <EnvPage pushToast={pushToast} localIP={localIP} setLocalIP={setLocalIP} />}
            {page === "mock" && <MockPage pushToast={pushToast} />}
            {page === "provision" && (
              <ErrorBoundary>
                <ProvisionPage pushToast={pushToast} localIP={localIP} />
              </ErrorBoundary>
            )}
            {page === "verify" && <VerifyPage pushToast={pushToast} localIP={localIP} />}
            {page === "history" && <HistoryPage pushToast={pushToast} />}
            {page === "cases" && (
              <TestCasesPage
                pushToast={pushToast}
                selectedIds={selectedCaseIds}
                setSelectedIds={setSelectedCaseIds}
                goToRuns={() => setPage("runs")}
              />
            )}
            {page === "runs" && (
              <TestRunsPage
                pushToast={pushToast}
                selectedIds={selectedCaseIds}
                setSelectedIds={setSelectedCaseIds}
                loggedIn={loggedIn}
                localIP={localIP}
              />
            )}
          </div>
        </section>
      </main>
      <Toaster toasts={toasts} dismiss={dismiss} />
    </div>
  );
}

export default App;