/** 登录页（spec/07 §3.1）。 */

import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { authApi, healthApi, type OauthLogView } from '../api/endpoints';
import { ApiError } from '../api/client';
import { oauthErrorText, sse } from '../api/sse';
import { landingPath, useSession } from '../store/session';

type Tab = 'zhihu' | 'dev';

/** DEV 环境下的 OAuth 调试面板：一眼看出回调配置与失败环节。 */
function OauthDebugPanel() {
  const [data, setData] = useState<OauthLogView | null>(null);
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setFailed(false);
    authApi
      .oauthLog()
      .then(setData)
      .catch(() => {
        setData(null);
        setFailed(true);
      });
  };

  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const yes = (v: boolean) => (v ? '✅' : '❌');

  return (
    <details
      className="card mt-4 overflow-hidden"
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-ink">
        OAuth 调试日志 <span className="ml-1 text-xs font-normal text-muted">（仅 DEV_MODE）</span>
      </summary>
      <div className="space-y-3 border-t border-black/5 px-4 py-3 text-xs">
        {failed && <p className="text-muted">后端未开启 DEV_MODE，或该接口不可用。</p>}
        {data && (
          <>
            <dl className="grid gap-1.5">
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-muted">回调地址</dt>
                <dd className="break-all font-mono text-[11px] text-ink">{data.redirect_uri}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-muted">站点地址</dt>
                <dd className="break-all font-mono text-[11px] text-ink">{data.public_base_url}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-muted">cookie Secure</dt>
                <dd className="text-ink">{String(data.cookie_secure)}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-28 shrink-0 text-muted">凭证</dt>
                <dd className="text-ink">
                  App ID {yes(data.app_id_configured)} · App Key {yes(data.app_key_configured)} ·
                  Access Secret {yes(data.access_secret_configured)}
                </dd>
              </div>
            </dl>
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-muted">最近事件（新→旧）</span>
                <button type="button" className="btn-outline text-[11px]" onClick={load}>
                  刷新
                </button>
              </div>
              {data.entries.length === 0 ? (
                <p className="text-muted">还没有记录。去点一次「使用知乎账号登录」再回来刷新。</p>
              ) : (
                <ul className="max-h-52 space-y-1.5 overflow-auto">
                  {data.entries.map((entry, i) => (
                    <li key={`${entry.at}-${i}`} className="rounded-lg bg-black/[.03] px-2 py-1.5">
                      <span className="font-mono text-[10px] text-muted">{entry.at}</span>
                      <span className="ml-2 font-medium text-ink">{entry.event}</span>
                      <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] text-muted">
                        {Object.entries(entry)
                          .filter(([k]) => k !== 'at' && k !== 'event')
                          .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
                          .join('  ')}
                      </pre>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </>
        )}
      </div>
    </details>
  );
}

export default function Login() {
  const [params] = useSearchParams();
  const setUser = useSession((s) => s.setUser);
  const [tab, setTab] = useState<Tab>('zhihu');
  const [devMode, setDevMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const oauthError = oauthErrorText(params.get('reason'));
  const oauthFailed = params.get('error') === 'oauth_failed';

  const [devName, setDevName] = useState('');

  useEffect(() => {
    void healthApi
      .check()
      .then((h) => setDevMode(Boolean(h.dev_mode)))
      .catch(() => setDevMode(false));
    void sse;
  }, []);

  const errText = (err: unknown, fallback: string) =>
    err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;

  return (
    <div className="flex min-h-full items-center justify-center bg-gradient-to-br from-brand-50 via-paper to-white px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-brand-500 text-2xl text-white shadow-lg shadow-brand-500/30">
            平
          </div>
          <h1 className="text-2xl font-semibold text-ink">平行校园</h1>
          <p className="mt-1.5 text-sm text-muted">
            把你的知乎人格，投进一个会自己运转的校园
          </p>
        </div>

        <div className="card p-6">
          {(oauthFailed || oauthError) && (
            <div className="mb-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">
              {oauthError ?? '登录失败，请重试'}
            </div>
          )}

          {tab === 'zhihu' && (
            <div className="space-y-4">
              <button
                type="button"
                className="btn-primary w-full py-2.5"
                onClick={() => {
                  window.location.href = '/api/auth/zhihu/login';
                }}
              >
                使用知乎账号登录
              </button>
              <p className="text-center text-xs leading-relaxed text-muted">
                仅读取你的公开创作、关注与收藏，用于生成人格文件；可随时删除
              </p>
            </div>
          )}

          {tab === 'dev' && devMode && (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                setBusy(true);
                setError(null);
                authApi
                  .devLogin(devName.trim() || '测试同学')
                  .then((u) => {
                    setUser(u);
                    window.location.href = landingPath(u);
                  })
                  .catch((err) => setError(errText(err, '登录失败')))
                  .finally(() => setBusy(false));
              }}
            >
              <input
                className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm outline-none focus:border-brand-500"
                placeholder="你的名字"
                value={devName}
                onChange={(e) => setDevName(e.target.value)}
              />
              <button type="submit" className="btn-primary w-full py-2.5" disabled={busy}>
                {busy ? '进入中…' : '开发登录'}
              </button>
              <p className="text-center text-xs text-muted">DEV_MODE 已开启，不会写真实数据</p>
            </form>
          )}

          {error && (
            <div className="mt-4 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <div className="mt-5 flex items-center justify-center gap-3 border-t border-black/5 pt-4 text-xs text-muted">
            <button
              type="button"
              className={tab === 'zhihu' ? 'font-medium text-brand-600' : 'hover:text-ink'}
              onClick={() => setTab('zhihu')}
            >
              知乎登录
            </button>
            <span className="text-black/10">|</span>
            <details className="inline-block">
              <summary className="cursor-pointer list-none hover:text-ink">其他方式</summary>
              <a href="/admin" className="mt-2 block text-brand-600">管理员入口</a>
              <div className="mt-2 flex gap-3">
                {devMode && (
                  <button
                    type="button"
                    className={tab === 'dev' ? 'font-medium text-brand-600' : 'hover:text-ink'}
                    onClick={() => setTab('dev')}
                  >
                    开发登录
                  </button>
                )}
              </div>
            </details>
          </div>
        </div>

        {devMode && <OauthDebugPanel />}
      </div>
    </div>
  );
}
