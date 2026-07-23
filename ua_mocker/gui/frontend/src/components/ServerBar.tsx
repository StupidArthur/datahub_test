import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Copy, Play, Square } from 'lucide-react'
import type { ServerStatus } from '@/lib/api'

interface Props {
  status: ServerStatus
  busy: boolean
  onStart: () => void
  onStop: () => void
  onCopy: () => void
}

/** 顶栏：运行状态徽标 + endpoint（可复制）+ 启停主操作 */
export function ServerBar({ status, busy, onStart, onStop, onCopy }: Props) {
  return (
    <header className="flex items-center gap-3 px-7 py-4 border-b border-border bg-card">
      <span
        className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
          status.running ? 'bg-[#2f9e6f]' : 'bg-muted-foreground/30'
        }`}
      />
      <Badge variant="secondary" className="flex-shrink-0">
        {status.running ? '运行中' : '已停止'}
      </Badge>

      {status.running ? (
        <>
          <code className="text-[12.5px] text-muted-foreground truncate">{status.endpoint}</code>
          <Button variant="outline" size="sm" onClick={onCopy} className="flex-shrink-0">
            <Copy className="w-4 h-4 mr-1.5" />
            复制
          </Button>
          <span className="text-[12px] text-muted-foreground/70 flex-shrink-0">
            {status.nodeCount} 节点 · PID {status.pid}
          </span>
        </>
      ) : (
        <span className="text-[12.5px] text-muted-foreground truncate">
          启动后，外部 OPC UA 客户端可连接 endpoint 获取 26 个全类型模拟节点
        </span>
      )}

      <div className="flex-1" />

      {status.running ? (
        <Button variant="destructive" size="sm" disabled={busy} onClick={onStop}>
          <Square className="w-4 h-4 mr-1.5" />
          停止
        </Button>
      ) : (
        <Button size="sm" disabled={busy} onClick={onStart}>
          <Play className="w-4 h-4 mr-1.5" />
          启动
        </Button>
      )}
    </header>
  )
}
