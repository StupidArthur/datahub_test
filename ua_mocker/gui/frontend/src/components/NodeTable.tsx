import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { EmptyState } from '@/components/EmptyState'
import type { NodeSpec } from '@/lib/api'

/** 节点列表：固定 26 节点（13 类型 × 自变化/可写）的静态展示 */
export function NodeTable({ nodes }: { nodes: NodeSpec[] }) {
  return (
    <section className="bg-card border border-border rounded-lg">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <h2 className="text-[14px] font-semibold">节点列表</h2>
        <Badge variant="secondary">{nodes.length}</Badge>
      </div>

      {nodes.length === 0 ? (
        <EmptyState icon="∅" title="暂无节点" />
      ) : (
        <ScrollArea className="max-h-[52vh]">
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-card">
              <tr className="text-left text-[12px] text-muted-foreground border-b border-border">
                <th className="px-4 py-2 font-medium">NodeId</th>
                <th className="px-4 py-2 font-medium">类型</th>
                <th className="px-4 py-2 font-medium">模式</th>
                <th className="px-4 py-2 font-medium">默认值</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map((n) => (
                <tr
                  key={n.nodeId}
                  className="border-b border-border/60 last:border-0 hover:bg-secondary/40 transition-colors"
                >
                  <td className="px-4 py-2 font-mono text-[12.5px]">{n.nodeId}</td>
                  <td className="px-4 py-2">{n.type}</td>
                  <td className="px-4 py-2">
                    {n.mode === 'change' ? (
                      <Badge>自动变化</Badge>
                    ) : (
                      <Badge variant="outline">可写</Badge>
                    )}
                  </td>
                  <td className="px-4 py-2 font-mono text-[12.5px] text-muted-foreground">
                    {n.default || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollArea>
      )}
    </section>
  )
}
