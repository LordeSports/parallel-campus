/** 应用骨架：TopBar（固定 56px）+ NavTabs + 内容出口（spec/07 §2）。 */

import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { authApi } from '../api/endpoints';
import { useSession } from '../store/session';
import { SPEED_BADGE, moodEmoji, useWorld, weatherLabel } from '../store/world';

const TABS = [
  { to: '/campus', label: '校园' },
  { to: '/wall', label: '校园墙' },
  { to: '/diary', label: '我的分身' },
  { to: '/report', label: '匹配报告' },
];

/** 观察者没有分身，隐藏只对自己分身有意义的页签。 */
const OBSERVER_TABS = TABS.filter((t) => t.to === '/campus' || t.to === '/wall');

function SpeedBadge() {  const state = useWorld((s) => s.state);
  const connected = useWorld((s) => s.connected);
  if (!connected) {
    return (
      <span className="chip bg-amber-50 text-amber-700" title="连接中…">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
        连接中…
      </span>
    );
  }
  const mode = state?.speed_mode ?? 'idle';
  const badge = SPEED_BADGE[mode] ?? SPEED_BADGE.idle;
  return (
    <span className="chip bg-black/5" title={badge.text}>
      <span className={`h-1.5 w-1.5 rounded-full ${badge.dot}`} />
      {badge.text}
    </span>
  );
}

/** 身份徽标：点击在「观察者 / 玩家」之间切换。 */
function RoleChip() {
  const user = useSession((s) => s.user);
  const setUser = useSession((s) => s.setUser);
  const [busy, setBusy] = useState(false);
  if (!user) return null;
  const isObserver = user.role === 'observer';

  const toggle = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const next = isObserver ? 'player' : 'observer';
      const updated = await authApi.setRole(next);
      setUser(updated);
      // 切到玩家但还没人格/分身 → 去完成投放流程
      if (next === 'player' && (!updated.has_persona || !updated.character_id)) {
        window.location.href = '/persona';
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      className={`chip ${isObserver ? 'bg-slate-100 text-slate-600' : 'bg-brand-50 text-brand-600'}`}
      title={
        isObserver
          ? '当前是观察者 · 点击切换为玩家（需生成人格并投放分身）'
          : '当前是玩家 · 点击切换为观察者（不再投放分身，只看世界）'
      }
    >
      {busy ? '切换中…' : isObserver ? '观察者' : '玩家'}
    </button>
  );
}

export default function AppShell() {
  const user = useSession((s) => s.user);
  const logout = useSession((s) => s.logout);
  const navigate = useNavigate();
  const location = useLocation();
  const state = useWorld((s) => s.state);
  const me = useWorld((s) => (user?.character_id ? s.characters[user.character_id] : undefined));

  const weather = state?.weather;
  const degraded = state?.degraded;
  const isObserver = user?.role === 'observer';
  const tabs = isObserver ? OBSERVER_TABS : TABS;

  return (
    <div className="flex min-h-full flex-col bg-paper">
      {/* TopBar */}
      <header className="glass-header sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-black/5 px-4 backdrop-blur">
        <button
          type="button"
          onClick={() => navigate('/campus')}
          className="flex items-center gap-2 text-base font-semibold text-ink"
        >
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-500 text-sm text-white">
            平
          </span>
          平行校园
        </button>

        <span className="hidden text-sm text-muted sm:inline">
          {state ? `第${state.day}天 · ${state.time_label}` : '—'}
        </span>
        {weather && (
          <span className="hidden text-sm text-muted md:inline">{weatherLabel(weather)}</span>
        )}

        <div className="ml-auto flex items-center gap-2">
          {(state?.active_events ?? []).slice(0, 2).map((ev) => (
            <span key={ev.id} className="chip hidden bg-brand-50 text-brand-600 lg:inline-flex">
              📣 {ev.title}
            </span>
          ))}
          <SpeedBadge />
          <RoleChip />
          <NavLink to="/admin" className="btn-ghost px-2 text-xs">管理</NavLink>

          {me && (
            <span className="chip bg-amber-50 text-amber-700" title="我的分身">
              {moodEmoji(me.mood?.valence, me.mood?.arousal)} 我
            </span>
          )}

          <div className="relative">
            <button
              type="button"
              onClick={() => navigate('/diary')}
              className="grid h-8 w-8 place-items-center overflow-hidden rounded-full bg-black/5 text-sm"
              title={user?.display_name ?? '我'}
            >
              {(user?.display_name ?? '我').slice(0, 1)}
            </button>
          </div>

          <button
            type="button"
            className="btn-ghost px-2 py-1 text-xs"
            onClick={() => {
              void logout().then(() => navigate('/login'));
            }}
          >
            退出
          </button>
        </div>
      </header>

      {/* 降级黄条（spec/07 §2） */}
      {degraded && (
        <div className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-800">
          校园信号不好，角色们按日程行动中
        </div>
      )}

      {/* NavTabs */}
      <nav className="sticky top-14 z-20 flex shrink-0 gap-1 border-b border-black/5 bg-white/65 px-3 backdrop-blur">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              [
                '-mb-px border-b-2 px-3 py-2.5 text-sm transition-colors',
                isActive
                  ? 'border-brand-500 font-medium text-brand-600'
                  : 'border-transparent text-muted hover:text-ink',
              ].join(' ')
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      <main className="min-h-0 flex-1">
        <div key={location.pathname} className="page-enter h-full">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
