/** 实时动态流（spec/07 §3.3）：最近 50 条 SSE 事件。 */

import { useState } from 'react';

import { useWorld } from '../store/world';

export default function LiveFeed() {
  const feed = useWorld((s) => s.feed);
  const dialogues = useWorld((s) => s.dialogues);
  const characters = useWorld((s) => s.characters);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-black/5 px-3 py-2">
        <h2 className="text-sm font-medium text-ink">校园动态</h2>
        <span className="chip bg-black/5">{feed.length}/50</span>
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {feed.length === 0 && (
          <p className="px-2 py-8 text-center text-xs text-muted">
            校园刚开始运转，稍等一会儿就有动静
          </p>
        )}

        <ul className="space-y-0.5">
          {feed.map((item) => {
            const dlg = item.dialogueId ? dialogues[item.dialogueId] : undefined;
            const expanded = open === item.key && dlg;
            return (
              <li key={item.key} className="animate-fade-up">
                <button
                  type="button"
                  disabled={!item.dialogueId}
                  onClick={() => setOpen(expanded ? null : item.key)}
                  className={[
                    'flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs',
                    item.dialogueId ? 'hover:bg-black/5' : 'cursor-default',
                  ].join(' ')}
                >
                  <span className="mt-px shrink-0">{item.icon}</span>
                  <span className="min-w-0 flex-1">
                    <span className="mr-1.5 text-[10px] text-muted">{item.timeLabel}</span>
                    <span className="text-ink">{item.text}</span>
                  </span>
                  {item.dialogueId && <span className="shrink-0 text-[10px] text-muted">▾</span>}
                </button>

                {expanded && dlg && (
                  <ul className="mb-1 ml-6 space-y-1 border-l border-black/10 pl-3">
                    {dlg.turns.map((t) => (
                      <li key={t.index} className="text-xs text-ink">
                        <span className="mr-1 text-[10px] text-brand-600">
                          {characters[t.speakerId]?.name ?? '某人'}
                        </span>
                        {t.text}
                      </li>
                    ))}
                    {dlg.ended && (
                      <li className="text-[10px] text-muted">
                        聊天结束（{dlg.endedBecause || '自然收尾'}）
                      </li>
                    )}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
