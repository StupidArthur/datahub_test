// LogViewer.tsx - 增量日志查看器。
import { useEffect, useRef, useState } from "react";
import { automation } from "../../lib/api";

export interface LogViewerProps {
  api: { readRunLog: (req: automation.ReadLogRequest) => Promise<automation.LogChunk> };
  runId: number;
  refreshMs?: number;
  maxLines?: number;
  autoScroll?: boolean;
}

export function LogViewer({ api, runId, refreshMs = 2000, maxLines = 500, autoScroll: auto = true }: LogViewerProps) {
  const [content, setContent] = useState<string>("");
  const [offset, setOffset] = useState<number>(0);
  const [eof, setEof] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: any = null;

    async function pull() {
      try {
        const chunk = await api.readRunLog({ runId, offset, limit: 64 * 1024 });
        if (cancelled) return;
        if (chunk.content) {
          setContent((prev) => {
            const next = prev + chunk.content;
            const lines = next.split(/\r?\n/);
            if (lines.length > maxLines) {
              return lines.slice(lines.length - maxLines).join("\n");
            }
            return next;
          });
        }
        setOffset(chunk.next);
        setEof(chunk.eof);
        if (auto && containerRef.current) {
          containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
      } catch (e) {
        // ignore;下次再试
      }
      if (!cancelled && !eof) {
        timer = setTimeout(pull, refreshMs);
      }
    }
    pull();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, offset, eof, refreshMs, maxLines, auto]);

  return (
    <div
      ref={containerRef}
      className="bg-black text-green-200 font-mono text-xs p-3 rounded-md h-72 overflow-auto whitespace-pre-wrap"
    >
      {content || "(等待日志)"}
    </div>
  );
}