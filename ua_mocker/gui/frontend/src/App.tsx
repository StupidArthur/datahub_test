import { useCallback, useEffect, useState } from 'react'
import { ToastProvider, useToast } from '@/components/Toast'
import { ServerBar } from '@/components/ServerBar'
import { SettingsForm } from '@/components/SettingsForm'
import { NodeTable } from '@/components/NodeTable'
import { api, type NodeSpec, type ServerStatus, type Settings } from '@/lib/api'

// 状态轮询间隔：感知服务进程意外退出
const POLL_MS = 3000

const EMPTY_STATUS: ServerStatus = { running: false, endpoint: '', nodeCount: 0, pid: 0 }

function AppContent() {
  const toast = useToast()
  const [status, setStatus] = useState<ServerStatus>(EMPTY_STATUS)
  const [settings, setSettings] = useState<Settings>({ port: 0, cycleMs: 0 })
  const [nodes, setNodes] = useState<NodeSpec[]>([])
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.getServerStatus())
    } catch {
      // 轮询失败静默（绑定层不会抛业务错误，仅防御性处理）
    }
  }, [])

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {})
    api.listNodes().then(setNodes).catch(() => {})
    refresh()
    const t = setInterval(refresh, POLL_MS)
    return () => clearInterval(t)
  }, [refresh])

  const handleStart = useCallback(async () => {
    setBusy(true)
    try {
      const res = await api.startServer()
      if (res.ok) {
        toast(`服务启动成功 · ${res.nodeCount} 节点`, 'success')
      } else {
        toast(res.error || '启动失败', 'error')
      }
    } catch (e) {
      toast(String(e), 'error')
    } finally {
      setBusy(false)
      refresh()
    }
  }, [refresh, toast])

  const handleStop = useCallback(async () => {
    setBusy(true)
    try {
      const res = await api.stopServer()
      if (res.ok) {
        toast('服务已停止', 'info')
      } else {
        toast(res.error || '停止失败', 'error')
      }
    } catch (e) {
      toast(String(e), 'error')
    } finally {
      setBusy(false)
      refresh()
    }
  }, [refresh, toast])

  const handleSaveSettings = useCallback(
    async (port: number, cycleMs: number) => {
      try {
        const res = await api.setSettings(port, cycleMs)
        if (res.ok) {
          setSettings({ port, cycleMs })
          toast('参数已保存', 'success')
        } else {
          toast(res.error || '保存失败', 'error')
        }
      } catch (e) {
        toast(String(e), 'error')
      }
    },
    [toast],
  )

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(status.endpoint)
      toast('endpoint 已复制', 'success')
    } catch {
      toast('复制失败', 'error')
    }
  }, [status.endpoint, toast])

  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <ServerBar
        status={status}
        busy={busy}
        onStart={handleStart}
        onStop={handleStop}
        onCopy={handleCopy}
      />
      <main className="flex-1 min-h-0 overflow-y-auto px-7 py-5 space-y-4">
        <SettingsForm
          settings={settings}
          disabled={status.running || busy}
          onSave={handleSaveSettings}
        />
        <NodeTable nodes={nodes} />
        <p className="text-[11.5px] text-muted-foreground/60 pb-2">
          自变化节点按周期更新：Boolean 翻转 · 数值 0~99 锯齿波 · 字符串 a~z 循环 · DateTime +1s
        </p>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  )
}
