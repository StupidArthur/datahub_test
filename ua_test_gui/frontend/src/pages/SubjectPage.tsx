// 被测对象页:自动登录--打开即登录,改信息即重试;密码存 localStorage。
import { useState, useEffect, useRef } from "react";
import { api, parseSubjectURL, bindings } from "../lib/api";
import { ToastKind } from "../components/Toast";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";

// 模块级:仅首次登录成功弹 toast,后续静默(切 tab 重挂载不重复弹)
let firstLoginDone = false;

export function SubjectPage({ pushToast, onLoggedIn }: {
  pushToast: (k: ToastKind, t: string) => void;
  onLoggedIn: (baseUrl: string, tenantId: string) => void;
}) {
  const [url, setUrl] = useState(localStorage.getItem("subject_url") || "http://10.10.58.153:31501");
  const [username, setUsername] = useState(localStorage.getItem("subject_user") || "admin");
  const [password, setPassword] = useState(localStorage.getItem("subject_pwd") || "");
  const [tenantId, setTenantId] = useState(localStorage.getItem("subject_tenant") || "");
  const [loading, setLoading] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);

  const parsed = parseSubjectURL(url);
  useEffect(() => {
    if (parsed.tenantId) setTenantId(parsed.tenantId);
  }, [parsed.tenantId]);

  const firstRun = useRef(true);
  async function doLogin() {
    if (!parsed.baseUrl) return;
    if (!password) {
      pushToast("error", "未保存密码,请输入密码");
      return;
    }
    setLoading(true);
    try {
      const res = await api.login({
        baseUrl: parsed.baseUrl || url, username, password,
        tenantId: tenantId || parsed.tenantId, timeoutSec: 10,
      } as bindings.LoginRequest);
      localStorage.setItem("subject_url", url);
      localStorage.setItem("subject_user", username);
      localStorage.setItem("subject_pwd", password);
      localStorage.setItem("subject_tenant", tenantId);
      setLoggedIn(true);
      onLoggedIn(res.baseUrl, res.tenantId);
      if (!firstLoginDone) {
        pushToast("success", "登录成功");
        firstLoginDone = true;
      }
    } catch (e) {
      setLoggedIn(false);
      pushToast("error", "登录失败: " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  // 打开即登录(首次立即);改 url/username/password 后防抖 600ms 自动重试
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      doLogin();
      return;
    }
    const t = setTimeout(doLogin, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, username, password]);

  return (
    <div className="flex flex-col gap-3.5 max-w-2xl">
      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-muted-foreground">URL(支持 http/https,可带租户信息)</label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)}
          placeholder="http://host:port 或 https://host:port/tenant/{id}" />
      </div>
      <div className="text-xs text-muted-foreground leading-relaxed">
        协议: <b className="text-primary font-semibold">{parsed.protocol || "-"}</b> &nbsp;|&nbsp; base_url: <b className="text-primary font-semibold">{parsed.baseUrl || "-"}</b> &nbsp;|&nbsp; 租户ID: <b className="text-primary font-semibold">{parsed.tenantId || "(无)"}</b>
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-muted-foreground">租户 ID(URL 带则自动填,可空)</label>
        <Input value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-muted-foreground">Username</label>
        <Input value={username} onChange={(e) => setUsername(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <label className="text-sm text-muted-foreground">Password</label>
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      <div className="flex items-center gap-3 mt-1">
        {loading && <Badge variant="secondary">登录中...</Badge>}
        {loggedIn && !loading && <Badge variant="success">已登录</Badge>}
        {!loggedIn && !loading && <Badge variant="destructive">未登录</Badge>}
      </div>
      <div className="text-xs text-muted-foreground">打开软件自动登录,修改信息自动重试。密码保存在本地(localStorage)。</div>
    </div>
  );
}
