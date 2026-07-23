// CaseTree.tsx - 测试用例章节树(左/侧边栏)。
import { useMemo } from "react";
import { automation } from "../../lib/api";
import { StatusBadge } from "./StatusBadge";

export interface CaseTreeProps {
  catalog: automation.Catalog | null;
  selectedIds: string[];
  onToggle: (caseId: string, checked: boolean) => void;
  onSelectChapter?: (chapterId: string) => void;
  filterText?: string;
}

export function CaseTree({ catalog, selectedIds, onToggle, onSelectChapter, filterText }: CaseTreeProps) {
  const filtered = useMemo(() => {
    if (!catalog) return [];
    const kw = (filterText || "").trim().toLowerCase();
    if (!kw) return catalog.chapters;
    return catalog.chapters
      .map((ch) => ({
        ...ch,
        cases: ch.cases.filter(
          (c) => c.id.toLowerCase().includes(kw) || c.title.toLowerCase().includes(kw) || (c.tags || []).some((t) => t.toLowerCase().includes(kw))
        ),
      }))
      .filter((ch) => ch.cases.length > 0);
  }, [catalog, filterText]);

  if (!catalog) {
    return <div className="text-sm text-muted-foreground">暂无 catalog</div>;
  }

  return (
    <div className="flex flex-col gap-2 text-sm">
      {filtered.map((ch) => (
        <div key={ch.id} className="border rounded-md">
          <div className="flex items-center justify-between px-3 py-2 bg-muted/40">
            <div>
              <div className="font-medium">{ch.id}</div>
              <div className="text-xs text-muted-foreground">{ch.title} · {ch.cases.length} 个用例</div>
            </div>
            {onSelectChapter && (
              <button
                className="text-xs px-2 py-1 rounded-md border hover:bg-accent"
                onClick={() => onSelectChapter(ch.id)}
              >
                选择本章节
              </button>
            )}
          </div>
          <ul className="divide-y">
            {ch.cases.map((c) => (
              <li key={c.id} className="flex items-center gap-2 px-3 py-2">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(c.id)}
                  onChange={(e) => onToggle(c.id, e.target.checked)}
                  className="rounded"
                />
                <div className="flex-1">
                  <div className="font-mono text-xs">{c.id}</div>
                  <div className="text-sm">{c.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {c.kind} · {c.implemented ? "已实现" : "未实现"} · timeout={c.timeoutSec}s
                  </div>
                </div>
                {!c.implemented && <StatusBadge status="BLOCKED" />}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}