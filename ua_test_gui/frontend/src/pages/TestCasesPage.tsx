// TestCasesPage.tsx - 测试用例浏览/选择页。
import { useEffect, useState } from "react";
import { api, automation } from "../lib/api";
import { CaseTree } from "../components/test/CaseTree";
import { ToastKind } from "../components/Toast";

export interface TestCasesPageProps {
  pushToast: (kind: ToastKind, text: string) => void;
  selectedIds: string[];
  setSelectedIds: (ids: string[]) => void;
  goToRuns: () => void;
}

export function TestCasesPage({ pushToast, selectedIds, setSelectedIds, goToRuns }: TestCasesPageProps) {
  const [catalog, setCatalog] = useState<automation.Catalog | null>(null);
  const [filterText, setFilterText] = useState("");
  const [detail, setDetail] = useState<automation.Case | null>(null);

  async function load() {
    try {
      const c = await api.listTestCases();
      setCatalog(c);
    } catch (e: any) {
      pushToast("error", `加载 catalog 失败: ${e?.message || e}`);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function toggle(id: string, on: boolean) {
    if (on) {
      setSelectedIds([...new Set([...selectedIds, id])]);
    } else {
      setSelectedIds(selectedIds.filter((x) => x !== id));
    }
  }

  function selectChapter(chapterId: string) {
    if (!catalog) return;
    const ids = catalog.chapters.find((c) => c.id === chapterId)?.cases.map((c) => c.id) || [];
    setSelectedIds([...new Set([...selectedIds, ...ids])]);
  }

  function selectAllImplemented() {
    if (!catalog) return;
    const ids = catalog.chapters.flatMap((c) => c.cases.filter((x) => x.implemented).map((x) => x.id));
    setSelectedIds([...new Set([...selectedIds, ...ids])]);
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-7 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <input
            className="flex-1 px-3 py-2 rounded-md border bg-background text-sm"
            placeholder="搜索 case id / 标题 / 标签"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
          />
          <button className="px-3 py-2 rounded-md border text-sm hover:bg-accent" onClick={load}>刷新</button>
          <button className="px-3 py-2 rounded-md border text-sm hover:bg-accent" onClick={selectAllImplemented}>
            选择全部已实现
          </button>
          <button className="px-3 py-2 rounded-md bg-primary text-primary-foreground text-sm" onClick={goToRuns}>
            使用所选用例创建任务 ({selectedIds.length})
          </button>
        </div>
        <CaseTree
          catalog={catalog}
          selectedIds={selectedIds}
          onToggle={toggle}
          onSelectChapter={selectChapter}
          filterText={filterText}
        />
      </div>
      <div className="col-span-5 border rounded-md p-4">
        {detail ? (
          <div className="flex flex-col gap-2 text-sm">
            <div className="font-mono">{detail.id}</div>
            <div className="font-medium">{detail.title}</div>
            <div className="text-xs text-muted-foreground">{detail.description || "(无描述)"}</div>
            <div className="text-xs text-muted-foreground">kind={detail.kind} · timeout={detail.timeoutSec}s</div>
            {detail.assertions?.length > 0 && (
              <div>
                <div className="text-xs font-medium mt-2">断言</div>
                <ul className="list-disc list-inside text-xs">
                  {detail.assertions.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            )}
            {detail.steps?.length > 0 && (
              <div>
                <div className="text-xs font-medium mt-2">步骤</div>
                <ul className="list-disc list-inside text-xs">
                  {detail.steps.map((s, i) => (
                    <li key={i}><span className="font-mono">{s.stepId}</span> · {s.title}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground">选择左侧用例以查看详情</div>
        )}
      </div>
    </div>
  );
}