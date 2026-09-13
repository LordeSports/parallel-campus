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

  // 已登录但未完成人格/投放：除 /persona 外一律回 /persona（spec/07 §1）
  const needPersona = !user.has_persona || !user.character_id;
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
  }, [user, bootstrapWorld, applyWorldEvent, applyAvatarEvent, setConnected]);

  if (!ready) return <FullScreen text="正在进入校园…" />;

  return (
    <Routes>
      <Route path="/login" element={<LoginRedirect />} />
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
