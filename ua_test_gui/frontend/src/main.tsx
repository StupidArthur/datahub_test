import React from 'react'
import {createRoot} from 'react-dom/client'
import './index.css'
import App from './App'

const container = document.getElementById('root')

const root = createRoot(container!)

// 全局兜底:任何未捕获的 JS 错误都渲染到页面上,方便无 devtools 时排查白屏。
function showGlobalError(message: string, stack?: string) {
  const el = document.createElement('div')
  el.className = 'p-4 text-sm'
  el.innerHTML = `
    <div class="font-bold text-destructive mb-2">应用启动失败</div>
    <pre class="bg-muted p-2 rounded overflow-auto whitespace-pre-wrap">${message}\n${stack || ''}</pre>
  `
  document.body.appendChild(el)
}

window.onerror = (msg, _url, _line, _col, err) => {
  showGlobalError(String(msg), err?.stack)
}
window.onunhandledrejection = (ev) => {
  showGlobalError(String(ev.reason), ev.reason?.stack)
}

root.render(
    <React.StrictMode>
        <App/>
    </React.StrictMode>
)
