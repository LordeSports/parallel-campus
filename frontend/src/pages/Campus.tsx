/** 校园页（spec/07 §3.3）：地图 + 动态流。 */

import { useState } from 'react';

import CharacterDrawer from '../components/CharacterDrawer';
import LiveFeed from '../components/LiveFeed';
import MapCanvas from '../components/MapCanvas';
import { useWorld } from '../store/world';
import { WEATHER_EMOJI } from '../store/world';

function BriefingCard() {
  const briefing = useWorld((s) => s.briefing);
  const [open, setOpen] = useState(true);
  if (!briefing) return null;

  return (
    <div className="card mx-3 mt-3 overflow-hidden">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-sm font-medium text-ink">
          昨日简报 · 第 {briefing.day} 天
        </span>
        <span className="text-xs text-muted">{open ? '收起' : '展开'}</span>
      </button>
      {open && (
        <p className="whitespace-pre-wrap border-t border-black/5 px-3 py-2.5 text-xs leading-relaxed text-ink">
          {briefing.text}
        </p>
      )}
    </div>
  );
}

function CampusHeader() {
  const state = useWorld((s) => s.state);
  const characters = useWorld((s) => s.characters);
  const feed = useWorld((s) => s.feed);
  const activeEvents = state?.active_events ?? [];
  const awake = Object.values(characters).filter((c) => !c.is_asleep).length;
  return <div className="mx-3 mt-3 grid gap-3 xl:grid-cols-[1fr_auto]">
    <div className="campus-hero rounded-[24px] px-5 py-4 text-white shadow-lg">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><p className="text-xs uppercase tracking-[.18em] text-white/60">Parallel Campus / live world</p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">今天的校园，正在自己长出来</h1>
          <p className="mt-1 max-w-xl text-sm text-white/75">每个 Agent 都有自己的日程、关系和临时念头。点开地图上的角色，看看他们此刻正在靠近谁。</p></div>
        <div className="rounded-2xl border border-white/20 bg-white/10 px-3 py-2 text-right backdrop-blur"><p className="text-xs text-white/60">{state?.time_label ?? '校园载入中'}</p><p className="mt-1 text-sm font-medium">{state ? `${WEATHER_EMOJI[state.weather.kind ?? 'sunny'] ?? '🌤'} ${state.weather.temp_c}° · ${awake} 人醒着` : '—'}</p></div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs"><span className="hero-pill">🧠 {Object.keys(characters).length} 个 Agent</span><span className="hero-pill">📡 {state?.observers ?? 0} 位观察者</span><span className="hero-pill">✦ {activeEvents.length} 个进行中场景</span><span className="hero-pill">↗ {feed.length} 条现场动态</span></div>
    </div>
    <div className="card flex min-w-[250px] items-center justify-between gap-4 px-4 py-3"><div><p className="text-xs text-muted">世界脉搏</p><p className="mt-1 text-sm font-medium text-ink">{state?.speed_mode === 'fast_forward' ? '正在快进' : state?.speed_mode === 'paused' ? '已暂停' : '自然运行中'}</p></div><div className="pulse-orb" aria-hidden="true"><span /></div></div>
  </div>;
}

function SceneRail() {
  const activeEvents = useWorld((s) => s.state?.active_events ?? []);
  const locations = useWorld((s) => s.locations);
  if (activeEvents.length === 0) return <div className="mx-3 mt-3 rounded-2xl border border-dashed border-black/10 bg-white/35 px-4 py-3 text-xs text-muted">管理员还没有布置临时场景。校园会按照日程继续运行。</div>;
  return <div className="scroll-thin mx-3 mt-3 flex gap-3 overflow-x-auto pb-1">{activeEvents.map((event) => <article key={event.id} className="scene-card min-w-[240px] shrink-0"><div className="flex items-start gap-3"><span className="scene-icon">✦</span><div className="min-w-0"><h2 className="truncate text-sm font-semibold text-ink">{event.title}</h2><p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted">{event.description || '校园里出现了一阵新的动静。'}</p><div className="mt-2 flex items-center gap-2 text-[10px] text-brand-600"><span>📍 {locations.find((location) => location.id === event.location_id)?.name ?? event.location_id ?? '校园'}</span><span>#{event.start_tick} → #{event.end_tick}</span></div></div></div></article>)}</div>;
}

export default function Campus() {
  const [picked, setPicked] = useState<string | null>(null);
  const loading = useWorld((s) => s.loading);
  const error = useWorld((s) => s.error);

  return (
    <div className="flex h-[calc(100vh-7.25rem)] flex-col">
      <BriefingCard />
      <CampusHeader />

      {error && (
        <div className="mx-3 mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      <SceneRail />

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* 地图 */}
        <div className="relative min-h-0 flex-1 p-3">
          <div className="card relative h-full overflow-hidden">
            <MapCanvas onPickCharacter={setPicked} />
            {loading && (
              <div className="absolute left-3 top-3 chip bg-white/90 text-muted">加载中…</div>
            )}
            <CharacterDrawer characterId={picked} onClose={() => setPicked(null)} />
          </div>
        </div>

        {/* 动态流：≥1024px 右侧 1/3（spec/07 §2） */}
        <div className="hidden min-h-0 w-80 shrink-0 border-l border-black/5 bg-white lg:block">
          <LiveFeed />
        </div>

        {/* <1024px：底部抽屉 */}
        <details className="border-t border-black/5 bg-white lg:hidden">
          <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium text-ink">
            校园动态
          </summary>
          <div className="h-72">
            <LiveFeed />
          </div>
        </details>
      </div>
    </div>
  );
}
