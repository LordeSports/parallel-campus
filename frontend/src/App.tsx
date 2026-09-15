/** 应用外壳：路由 + 守卫（spec/07 §1）。 */

import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import AppShell from './components/AppShell';
import Campus from './pages/Campus';
import Diary from './pages/Diary';
import Login from './pages/Login';
import Persona from './pages/Persona';
import Report from './pages/Report';
import Wall from './pages/Wall';
import { sse } from './api/sse';
import { worldApi } from './api/endpoints';
import { isKnownEvent } from './api/sse';
import { landingPath, useSession } from './store/session';
import { useWorld } from './store/world';
import { useAvatar } from './store/avatar';
import { useMap } from './store/map';
import Admin from './pages/Admin';

function FullScreen({ text }: { text: string }) {
  return (
    <div className="flex h-full items-center justify-center bg-paper">
      <div className="flex flex-col items-center gap-3 text-muted">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-black/10 border-t-brand-500" />
        <p className="text-sm">{text}</p>
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, ready, loading } = useSession();
  const location = useLocation();

  if (!ready || (loading && !user)) return <FullScreen text="正在进入校园…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;

  // 玩家：未完成人格/投放则回 /persona（spec/07 §1）；
  // 观察者不需要人格与分身，直接留在校园里看世界
  const needPersona =
    user.role !== 'observer' && (!user.has_persona || !user.character_id);
  if (needPersona && location.pathname !== '/persona') {
    return <Navigate to="/persona" replace />;
  }
  return <>{children}</>;
}

/** 登录后按状态分流。 */
function LoginRedirect() {
  const { user, ready, loading } = useSession();
  if (!ready || (loading && !user)) return <FullScreen text="正在进入校园…" />;
  if (!user) return <Login />;
  return <Navigate to={landingPath(user)} replace />;
}

export default function App() {
  const { user, ready, fetchMe } = useSession();
  const bootstrapWorld = useWorld((s) => s.bootstrap);
  const applyWorldEvent = useWorld((s) => s.applyEvent);
  const applyAvatarEvent = useAvatar((s) => s.applyEvent);
  const setConnected = useWorld((s) => s.setConnected);
  const refreshMapIfStale = useMap((s) => s.refreshIfStale);

  useEffect(() => {
    void fetchMe();
  }, [fetchMe]);

  // 已登录：拉首屏 + 开 SSE（spec/07 §3.3 / §5）
  useEffect(() => {
    if (!user) return;
    void bootstrapWorld();

    sse.start({
      onEvent: (evt) => {
        if (!isKnownEvent(evt.type)) return;
        applyWorldEvent(evt);
        applyAvatarEvent(evt);
        // 管理员保存地图 → 版本号变化 → 重新拉取
        if (evt.type === 'map_updated') {
          const v = Number((evt.data as { version?: unknown }).version ?? 0);
          if (Number.isFinite(v) && v > 0) refreshMapIfStale(v);
        }
      },
      onConnected: (v) => setConnected(v),
      getLastTick: () => useWorld.getState().lastTick,
      replay: async (sinceTick) => {
        try {
          const events = await worldApi.eventsSince(sinceTick, 300);
          for (const ev of events) {
            const kind = String((ev as { kind?: string }).kind ?? '');
            if (!isKnownEvent(kind)) continue;
            applyWorldEvent({
              id: String((ev as { id?: string }).id ?? ''),
              type: kind,
              data: ev as unknown as Record<string, unknown>,
              receivedAt: Date.now(),
            });
          }
        } catch (err) {
          console.debug('[sse] 回放失败', err);
        }
      },
    });

    return () => {
      sse.stop();
    };
  }, [user, bootstrapWorld, applyWorldEvent, applyAvatarEvent, setConnected, refreshMapIfStale]);

  if (!ready) return <FullScreen text="正在进入校园…" />;

  return (
    <Routes>
      <Route path="/login" element={<LoginRedirect />} />
      <Route path="/admin" element={<Admin />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/persona" element={<Persona />} />
        <Route path="/campus" element={<Campus />} />
        <Route path="/wall" element={<Wall />} />
        <Route path="/diary" element={<Diary />} />
        <Route path="/report" element={<Report />} />
      </Route>
      <Route path="*" element={<Navigate to="/campus" replace />} />
    </Routes>
  );
}
