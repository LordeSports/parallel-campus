/** 校园页（spec/07 §3.3）：校园地图 + 动态流。 */

import { useEffect, useState } from 'react';

import CharacterDrawer from '../components/CharacterDrawer';
import IsoMap from '../components/IsoMap';
import LiveFeed from '../components/LiveFeed';
import { useMap } from '../store/map';
import { useWorld } from '../store/world';
import { WEATHER_EMOJI } from '../store/world';

/** 昨日简报：默认折叠，避免一进页面就挤掉地图高度。 */
function BriefingCard() {
  const briefing = useWorld((s) => s.briefing);
  const [open, setOpen] = useState(false);
  if (!briefing) return null;

  return (
    <div className="card mx-3 mt-3 overflow-hidden">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-sm font-medium text-ink">昨日简报 · 第 {briefing.day} 天</span>
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

/** 紧凑状态条。原来是一块很高的蓝色横幅，把主显示区压得太小。 */
function StatusBar() {
  const state = useWorld((s) => s.state);
  const characters = useWorld((s) => s.characters);
  const feed = useWorld((s) => s.feed);
  const connected = useWorld((s) => s.connected);

  const awake = Object.values(characters).filter((c) => !c.is_asleep).length;
  const weather = state
    ? `${WEATHER_EMOJI[state.weather.kind ?? 'sunny'] ?? '🌤'} ${state.weather.temp_c}°`
    : '—';
  const speed =
    state?.speed_mode === 'fast_forward' ? '快进中' : state?.speed_mode === 'paused' ? '已暂停' : '运行中';
  const dotClass = connected ? 'bg-emerald-500' : 'bg-amber-400';

  return (
    <div className="mx-3 mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-2xl border border-black/5 bg-white/75 px-4 py-2.5 text-xs backdrop-blur">
      <span className="font-medium text-ink">今天的校园，正在自己长出来</span>
      <span className="text-muted">{state?.time_label ?? '载入中…'}</span>
      <span className="text-muted">{weather}</span>
      <span className="text-muted">{awake} 人醒着</span>
      <span className="text-muted">{Object.keys(characters).length} 个 Agent</span>
      <span className="text-muted">{state?.observers ?? 0} 位观察者</span>
      <span className="ml-auto flex items-center gap-2 text-muted">
        <span className={`h-1.5 w-1.5 rounded-full ${dotClass}`} aria-hidden="true" />
        {speed}
        <span>↗ {feed.length}</span>
      </span>
    </div>
  );
}

export default function Campus() {
  const [picked, setPicked] = useState<string | null>(null);
  const loading = useWorld((s) => s.loading);
  const error = useWorld((s) => s.error);
  const characters = useWorld((s) => s.characters);
  const map = useMap((s) => s.map);
  const mapLoading = useMap((s) => s.loading);
  const fetchMap = useMap((s) => s.fetch);

  useEffect(() => {
    if (!map) void fetchMap();
  }, [map, fetchMap]);

  const charList = Object.values(characters);

  return (
    <div className="flex h-[calc(100vh-7.25rem)] flex-col">
      <BriefingCard />
      <StatusBar />

      {error && (
        <div className="mx-3 mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      )}

      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* 校园地图：占满剩余空间，可拖动/滚轮缩放 */}
        <div className="relative min-h-0 flex-1 p-3">
          <div className="card relative h-full overflow-hidden">
            <IsoMap map={map} characters={charList} onPickCharacter={setPicked} />
            {loading || (mapLoading && !map) ? (
              <div className="absolute left-3 top-3 chip bg-white/90 text-muted">加载中…</div>
            ) : null}
            <CharacterDrawer characterId={picked} onClose={() => setPicked(null)} />
          </div>
        </div>

        {/* 动态流：≥1024px 右侧 1/3（spec/07 §2） */}
        <div className="hidden min-h-0 w-80 shrink-0 border-l border-black/5 bg-white lg:block">
          <LiveFeed />
        </div>

        {/* <1024px：底部抽屉 */}
        <details className="border-t border-black/5 bg-white lg:hidden">
          <summary className="cursor-pointer px-3 py-2.5 text-sm font-medium text-ink">校园动态</summary>
          <div className="h-72">
            <LiveFeed />
          </div>
        </details>
      </div>
    </div>
  );
}
