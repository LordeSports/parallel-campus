/** 校园页（spec/07 §3.3）：地图 + 动态流。 */

import { useState } from 'react';

import CharacterDrawer from '../components/CharacterDrawer';
import LiveFeed from '../components/LiveFeed';
import MapCanvas from '../components/MapCanvas';
import { useWorld } from '../store/world';

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

export default function Campus() {
  const [picked, setPicked] = useState<string | null>(null);
  const loading = useWorld((s) => s.loading);
  const error = useWorld((s) => s.error);
  const activeEvents = useWorld((s) => s.state?.active_events ?? []);

  return (
    <div className="flex h-[calc(100vh-7.25rem)] flex-col">
      <BriefingCard />

      {error && (
        <div className="mx-3 mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {activeEvents.length > 0 && (
        <div className="flex gap-2 overflow-x-auto px-3 pt-3 pb-1">
          {activeEvents.map((ev) => (
            <span key={ev.id} className="chip shrink-0 bg-brand-50 text-brand-600">
              📣 {ev.title}
            </span>
          ))}
        </div>
      )}

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
