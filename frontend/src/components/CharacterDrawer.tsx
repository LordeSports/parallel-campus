/** 角色详情抽屉（spec/07 §3.3）。 */

import { useEffect, useState } from 'react';

import { worldApi } from '../api/endpoints';
import type { CharacterDetailView } from '../api/types';
import { moodEmoji } from '../store/world';

export default function CharacterDrawer({
  characterId,
  onClose,
}: {
  characterId: string | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<CharacterDetailView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!characterId) {
      setDetail(null);
      return;
    }
    let alive = true;
    setDetail(null);
    setError(null);
    worldApi
      .character(characterId)
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : '加载失败');
      });
    return () => {
      alive = false;
    };
  }, [characterId]);

  if (!characterId) return null;

  const energy = detail?.energy ?? 0;

  return (
    <aside className="card absolute right-3 top-3 z-20 max-h-[calc(100%-1.5rem)] w-80 overflow-y-auto scroll-thin animate-fade-up">
      <div className="flex items-start gap-3 border-b border-black/5 p-4">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-black/5 text-xl">
          {detail ? moodEmoji(detail.mood?.valence, detail.mood?.arousal) : '…'}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-medium text-ink">
            {detail?.name ?? '加载中…'}
            {detail?.is_me && <span className="ml-1.5 text-xs text-amber-600">我</span>}
          </h3>
          <p className="mt-0.5 truncate text-xs text-muted">
            {detail?.archetype ?? detail?.identity?.major ?? '校园中的人'}
          </p>
        </div>
        <button type="button" className="btn-ghost -mr-2 -mt-1 px-2 py-1" onClick={onClose}>
          ✕
        </button>
      </div>

      {error && <p className="p-4 text-sm text-red-600">{error}</p>}

      {detail && (
        <div className="space-y-4 p-4 text-xs">
          <section>
            <h4 className="mb-1.5 text-[11px] font-medium text-muted">此刻</h4>
            <p className="text-ink">
              {detail.is_asleep ? '睡着了 💤' : (detail.activity ?? '在校园里晃悠')}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <span className="text-[10px] text-muted">精力</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-black/5">
                <div
                  className={[
                    'h-full rounded-full transition-all',
                    energy > 60 ? 'bg-green-500' : energy > 25 ? 'bg-amber-500' : 'bg-red-400',
                  ].join(' ')}
                  style={{ width: `${Math.max(0, Math.min(100, energy))}%` }}
                />
              </div>
              <span className="text-[10px] text-muted">{Math.round(energy)}</span>
            </div>
          </section>

          {detail.summary && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-medium text-muted">画像</h4>
              <p className="leading-relaxed text-ink">{detail.summary}</p>
            </section>
          )}

          {(detail.recent_memories ?? []).length > 0 && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-medium text-muted">最近记得的事</h4>
              <ul className="space-y-1.5">
                {(detail.recent_memories ?? []).slice(0, 5).map((m, i) => (
                  <li key={`${m.tick}-${i}`} className="flex gap-2">
                    <span className="chip shrink-0 px-1.5 py-0.5 text-[10px]">{m.kind}</span>
                    <span className="text-ink">{m.text}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {(detail.top_relationships ?? []).length > 0 && (
            <section>
              <h4 className="mb-1.5 text-[11px] font-medium text-muted">关系最近的人</h4>
              <ul className="space-y-1">
                {(detail.top_relationships ?? []).slice(0, 5).map((r) => (
                  <li key={r.character_id} className="flex items-center justify-between">
                    <span className="text-ink">{r.name}</span>
                    <span className="text-muted">{Math.round(r.affinity)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {detail.dialogue_id && (
            <p className="rounded-lg bg-brand-50 px-2.5 py-2 text-[11px] text-brand-600">
              正在聊天中 · 对话 #{detail.dialogue_id.slice(-6)}
            </p>
          )}
        </div>
      )}
    </aside>
  );
}
