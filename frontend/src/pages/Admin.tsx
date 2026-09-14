/** 独立管理员入口；不要求普通账号或投放分身。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { adminApi } from '../api/endpoints';
import type { ActiveEventView, AdminOverviewView, AdminSessionView, ApiSettingsView, LocationView, NpcView } from '../api/types';
import { Field, Section, fieldClass, type AdminAction } from '../components/AdminForms';
import AdminSimulation from '../components/AdminSimulation';
import AdminNpcs from '../components/AdminNpcs';
import AdminScenes from '../components/AdminScenes';
import AdminSettings from '../components/AdminSettings';
import MapEditor from '../components/MapEditor';

const tabs = ['总览', '校园地图', '模拟与环境', 'NPC 管理', '校园活动', 'API 配置'] as const;

function Overview({ data }: { data: AdminOverviewView }) {
  const usage = data.status.llm_today;
  const tiles = [
    ['活跃 Agent', data.counts.agents ?? 0], ['校园 NPC', data.counts.npcs ?? 0], ['真人分身', data.counts.players ?? 0],
    ['在线观众', data.world.observers ?? 0], ['清醒角色', data.counts.awake ?? 0], ['今日 LLM 调用', usage?.calls ?? 0],
    ['输入 Token', usage?.prompt_tokens ?? 0], ['输出 Token', usage?.completion_tokens ?? 0],
  ] as const;
  return <div className="space-y-6"><div className="grid grid-cols-2 gap-4 xl:grid-cols-4">{tiles.map(([label, value]) => <div className="card p-5" key={label}><p className="text-xs text-muted">{label}</p><p className="mt-3 text-3xl font-semibold tracking-tight tabular-nums">{value.toLocaleString()}</p></div>)}</div>
    <div className="grid gap-6 lg:grid-cols-2"><Section title="世界数据"><dl className="grid grid-cols-2 gap-4 text-sm">{[['帖子', data.counts.posts], ['对话', data.counts.dialogues], ['记忆', data.counts.memories], ['停用 NPC', data.counts.inactive_npcs]].map(([name, count]) => <div key={name}><dt className="text-muted">{name}</dt><dd className="mt-1 text-xl tabular-nums">{count ?? 0}</dd></div>)}</dl></Section>
      <Section title="今日知乎调用"><dl className="grid grid-cols-2 gap-4 text-sm">{Object.entries(data.status.zhihu_today ?? {}).map(([name, count]) => <div key={name}><dt className="text-muted">{{ hot_list: '热榜', zhihu_search: '搜索', zhida: '直答', user_data: '用户资料' }[name] ?? name}</dt><dd className="mt-1 text-xl tabular-nums">{count}</dd></div>)}</dl></Section></div>
    <Section title="模型用量 · 今日"><div className="overflow-auto"><table className="admin-table"><thead><tr><th>模型</th><th>调用次数</th><th>输入 Token</th><th>输出 Token</th></tr></thead><tbody>{data.usage_by_model.map(row => <tr key={row.model}><td>{row.model}</td><td>{row.calls}</td><td>{row.prompt_tokens.toLocaleString()}</td><td>{row.completion_tokens.toLocaleString()}</td></tr>)}</tbody></table></div>
      {data.usage_by_model.length === 0 && <p className="text-sm text-muted">今天还没有模型调用</p>}</Section>
    <Section title="最近调用"><div className="overflow-auto"><table className="admin-table"><thead><tr><th>时间</th><th>模型 / 任务</th><th>输入 / 输出</th><th>耗时</th><th>结果</th></tr></thead><tbody>{data.recent_usage.map(row => <tr key={row.id}><td className="whitespace-nowrap">{new Date(row.at).toLocaleString('zh-CN')}</td><td>{row.model}<span className="block text-xs text-muted">{row.template}</span></td><td>{row.prompt_tokens} / {row.completion_tokens}</td><td>{(row.latency_ms / 1000).toFixed(1)}s</td><td>{row.ok ? '成功' : '失败'}</td></tr>)}</tbody></table></div>
      {data.recent_usage.length === 0 && <p className="text-sm text-muted">暂时没有调用记录</p>}</Section>
  </div>;
}

export default function Admin() {
  const [session, setSession] = useState<AdminSessionView | null>(null);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [tab, setTab] = useState<typeof tabs[number]>('总览');
  const [overview, setOverview] = useState<AdminOverviewView | null>(null);
  const [settings, setSettings] = useState<ApiSettingsView | null>(null);
  const [npcs, setNpcs] = useState<NpcView[]>([]);
  const [locations, setLocations] = useState<LocationView[]>([]);
  const [scenes, setScenes] = useState<ActiveEventView[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const polling = useRef(false);
  const fetchSession = useCallback(() => { setError(null); void adminApi.session().then(setSession).catch(e => setError(e instanceof Error ? e.message : '无法连接后台')); }, []);
  useEffect(fetchSession, [fetchSession]);

  const refresh = useCallback(async () => {
    const [summary, config, agents, places, events] = await Promise.all([adminApi.overview(), adminApi.settings(), adminApi.npcs(), adminApi.locations(), adminApi.scenes()]);
    setOverview(summary); setSettings(config); setNpcs(agents); setLocations(places); setScenes(events);
  }, []);
  useEffect(() => {
    if (!session?.authenticated) return;
    let alive = true;
    const poll = async () => {
      if (polling.current) return;
      polling.current = true;
      try { await refresh(); }
      catch (e) { if (alive) { setError(e instanceof Error ? e.message : '加载失败'); if (e instanceof ApiError && e.status === 401) setSession({ enabled: true, authenticated: false }); } }
      finally { polling.current = false; }
    };
    void poll(); const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void poll(); }, 8000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [session?.authenticated, refresh]);

  const run: AdminAction = async (operation, success) => {
    setBusy(true); setError(null); setMessage(null);
    try { await operation(); await refresh(); setMessage(success); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '操作失败'); if (e instanceof ApiError && e.status === 401) setSession({ enabled: true, authenticated: false }); return false; }
    finally { setBusy(false); }
  };

  if (!session?.authenticated) return <div className="grid min-h-screen place-items-center bg-paper p-4"><div className="page-enter w-full max-w-md">
    <Link className="mb-6 inline-block text-sm text-muted" to="/campus">← 返回校园</Link><Section title="校园控制台" description="使用管理员账户管理这个世界。">
      {!session && !error && <p className="text-sm text-muted">正在连接后台…</p>}
      {session && !session.enabled && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">管理员登录尚未启用。在部署环境设置 ADMIN_USERNAME 和 ADMIN_PASSWORD，然后重启服务。</p>}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {!session && error && <button className="btn-outline" onClick={fetchSession}>重新连接</button>}
      {session?.enabled && <form className="space-y-4" onSubmit={e => { e.preventDefault(); setBusy(true); setError(null);
        void adminApi.login(username, password).then(value => { setSession(value); setPassword(''); }).catch(e => setError(e instanceof Error ? e.message : '登录失败')).finally(() => setBusy(false)); }}>
        <Field label="管理员账号"><input className={fieldClass} autoComplete="username" required value={username} onChange={e => setUsername(e.target.value)} /></Field>
        <Field label="管理员密码"><input className={fieldClass} type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></Field>
        <button className="btn-primary w-full" disabled={busy}>{busy ? '正在登录…' : '进入控制台'}</button>
      </form>}
    </Section></div></div>;

  return <div className="min-h-screen bg-paper text-ink"><header className="glass-header sticky top-0 z-30 border-b border-black/5 px-4 py-4 backdrop-blur-xl sm:px-8"><div className="mx-auto flex max-w-7xl items-center justify-between gap-3">
    <div><h1 className="text-lg font-semibold tracking-tight">平行校园 <span className="ml-2 text-sm font-normal text-muted">控制台</span></h1><p className="mt-1 text-xs text-muted">{overview?.world.time_label ?? '正在载入世界'} · {session.username}</p></div>
    <div className="flex gap-2"><Link to="/campus" className="btn-ghost">校园</Link><button className="btn-outline" disabled={busy} onClick={() => { setBusy(true); void adminApi.logout().then(() => { setSession({ enabled: true, authenticated: false }); setOverview(null); }).catch(e => setError(e instanceof Error ? e.message : '退出失败')).finally(() => setBusy(false)); }}>退出管理</button></div>
  </div></header><main className="mx-auto max-w-7xl px-4 py-6 sm:px-8">
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3"><nav className="flex max-w-full gap-1 overflow-auto rounded-2xl bg-black/5 p-1" aria-label="管理功能">{tabs.map(name => <button key={name} onClick={() => setTab(name)} aria-pressed={tab === name} className={`whitespace-nowrap rounded-xl px-4 py-2.5 text-sm transition-colors ${tab === name ? 'bg-white font-medium shadow-sm' : 'text-muted hover:text-ink'}`}>{name}</button>)}</nav>
      <button className="btn-outline" disabled={busy} onClick={() => void run(async () => undefined, '数据已刷新')}>刷新</button></div>
    {error && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {message && <p role="status" className="mb-5 rounded-xl bg-green-50 p-3 text-sm text-green-800">{message}</p>}
    {busy && <p role="status" className="mb-4 text-sm text-muted">正在应用修改，等待当前模拟步骤完成…</p>}
    {!overview || !settings ? <div className="card p-12 text-center text-muted">正在读取世界数据…</div> : <div key={tab} className="page-enter">
      {tab === '总览' && <Overview data={overview} />}
      {tab === '校园地图' && <MapEditor />}
      {tab === '模拟与环境' && <AdminSimulation overview={overview} settings={settings} busy={busy} run={run} />}
      {tab === 'NPC 管理' && <AdminNpcs npcs={npcs} locations={locations} busy={busy} run={run} />}
      {tab === '校园活动' && <AdminScenes scenes={scenes} locations={locations} busy={busy} run={run} />}
      {tab === 'API 配置' && <AdminSettings settings={settings} busy={busy} run={run} />}
    </div>}
  </main></div>;
}
