import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Settings } from '@/lib/api'

interface Props {
  settings: Settings
  disabled: boolean
  onSave: (port: number, cycleMs: number) => void
}

/** 参数区：端口 / 更新周期，运行中禁用（后端同样拦截） */
export function SettingsForm({ settings, disabled, onSave }: Props) {
  const [port, setPort] = useState(String(settings.port))
  const [cycle, setCycle] = useState(String(settings.cycleMs))

  // 后端参数变化时（如首次加载）同步本地输入
  useEffect(() => {
    setPort(String(settings.port))
    setCycle(String(settings.cycleMs))
  }, [settings])

  const save = () => {
    const p = Number(port)
    const c = Number(cycle)
    if (!Number.isInteger(p) || !Number.isInteger(c)) return
    onSave(p, c)
  }

  return (
    <section className="bg-card border border-border rounded-lg p-4 flex items-end gap-4 flex-wrap">
      <div className="space-y-1.5">
        <Label htmlFor="port">端口</Label>
        <Input
          id="port"
          className="w-28 font-mono"
          value={port}
          disabled={disabled}
          onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="cycle">更新周期 (ms)</Label>
        <Input
          id="cycle"
          className="w-32 font-mono"
          value={cycle}
          disabled={disabled}
          onChange={(e) => setCycle(e.target.value.replace(/\D/g, ''))}
        />
      </div>
      <Button variant="outline" size="sm" disabled={disabled} onClick={save}>
        保存
      </Button>
      {disabled && (
        <span className="text-[12px] text-muted-foreground">服务运行中，停止后可编辑参数</span>
      )}
    </section>
  )
}
