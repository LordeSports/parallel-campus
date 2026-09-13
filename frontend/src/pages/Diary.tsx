/** 我的分身：日记（spec/07 §3.5）。 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import type { DiaryEntryView } from '../api/types';
import MoodChart from '../components/MoodChart';
import Toast from '../components/Toast';
import { useAvatar } from '../store/avatar';
import { useSession } from '../store/session';
import { moodEmoji, useWorld } from '../store/world';

const TYPE_ICON: Record<string, string> = {
  move: '🚶',
  talk: '💬',
  post: '📝',
  dm: '💌',
  event: '📣',
  whisper: '🗣',
  like: '👍',
  comment: '💭',
  search_zhihu: '🔍',
  do: '🎯',
  idle: '…',
};

function Timeline({ entries }: { entries: DiaryEntryView[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (entries.length === 0) {
    return <p className="py-8 text-center text-xs text-muted">今天还没有记录</p>;
  }
  return (
    <ol className="space-y-2">
      {entries.map((e, i) => {
        const key = `${e.tick}-${i}`;
        const turns = (e.payload?.turns as { text: string }[] | undefined) ?? undefined;
        const expanded = open === key;
        return (
          <li key={key} className="flex gap-3">
            <span className="w-10 shrink-0 pt-0.5 text-right text-[10px] text-muted">
              {e.time_label ?? `#${e.tick}`}
            </span>
            <span className="shrink-0 text-sm">{TYPE_ICON[e.type] ?? '·'}</span>
            <div className="min-w-0 flex-1">
              <p className="text-xs leading-relaxed text-ink">{e.text}</p>
              {turns && turns.length > 0 && (
                <>
                  <button
                    type="button"
                    className="mt-1 text-[10px] text-brand-600 hover:underline"
                    onClick={() => setOpen(expanded ? null : key)}
                  >
                    {expanded ? '收起对白' : `展开对白（${turns.length} 句）`}
                  </button>
                  {expanded && (
                    <ul className="mt-1.5 space-y-1 border-l border-black/10 pl-3">
                      {turns.map((t, j) => (
                        <li key={j} className="text-xs text-ink">
                          {t.text}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function WhisperBox() {
  const me = useAvatar((s) => s.me);
  const whisper = useAvatar((s) => s.whisper);
  const replies = useAvatar((s) => s.whisperReplies);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const left = me?.whispers_left_today ?? 0;

  return (
    <div className="card mt-4 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-medium text-ink">给分身递个耳语</h3>
        <span className="chip bg-black/5">今天还剩 {left} 次</span>
      </div>

      {pending && (
        <p className="mb-2 rounded-lg bg-brand-50 px-2.5 py-1.5 text-[11px] text-brand-600">
          已传达，等待分身回应…
        </p>
      )}

      {replies.length > 0 && (
        <ul className="mb-2 space-y-1.5">
          {replies.slice(0, 3).map((r) => (
            <li key={r.id} className="rounded-lg bg-black/5 px-2.5 py-1.5 text-[11px] text-ink">
              🗣 {r.text}
            </li>
          ))}
        </ul>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim() || left <= 0) return;
          setBusy(true);
          setPending(text.trim());
          whisper(text.trim())
            .then(() => setText(''))
            .catch((err) => setToast(err instanceof Error ? err.message : '发送失败'))
            .finally(() => setBusy(false));
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-full border border-black/10 px-3 py-2 text-xs outline-none focus:border-brand-500"
          placeholder="你想让 TA 做什么？（≤80 字）"
          maxLength={80}
          value={text}
          disabled={left <= 0}
          onChange={(e) => setText(e.target.value)}
        />
        <button type="submit" className="btn-primary px-4 text-xs" disabled={busy || left <= 0}>
          递过去
        </button>
      </form>

      {toast && <Toast text={toast} onClose={() => setToast(null)} />}
    </div>
  );
}

export default function Diary() {
  const user = useSession((s) => s.user);
  const me = useAvatar((s) => s.me);
  const diary = useAvatar((s) => s.diary);
  const fetchMe = useAvatar((s) => s.fetchMe);
  const fetchDiary = useAvatar((s) => s.fetchDiary);
  const characters = useWorld((s) => s.characters);
  const state = useWorld((s) => s.state);
  const [day, setDay] = useState<number | undefined>(undefined);

  useEffect(() => {
    void fetchMe();
  }, [fetchMe]);

  useEffect(() => {
    void fetchDiary(day);
  }, [day, fetchDiary]);

  const myChar = user?.character_id ? characters[user.character_id] : undefined;
  const today = state?.day ?? 1;
  const days = Array.from({ length: Math.max(1, today) }, (_, i) => i + 1);

  if (!user?.character_id) {
    return (
      <div className="mx-auto max-w-xl px-3 py-16 text-center">
        <div className="card p-8">
          <p className="text-3xl">🌱</p>
          <h2 className="mt-3 text-base font-medium text-ink">分身还没投放</h2>
          <p className="mt-1.5 text-sm text-muted">
            先把知乎人格投进校园，TA 才会开始写日记
          </p>
          <Link to="/persona" className="btn-primary mt-5 inline-flex">
            去投放分身
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-3 py-4">
      {/* 分身卡 */}
      <div className="card mb-4 flex items-center gap-3 p-4">
        <div className="grid h-12 w-12 place-items-center rounded-full bg-black/5 text-2xl">
          {moodEmoji(myChar?.mood?.valence, myChar?.mood?.arousal)}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-base font-medium text-ink">
            {me?.name ?? myChar?.name ?? '我的分身'}
          </h1>
          <p className="mt-0.5 truncate text-xs text-muted">
            {myChar?.is_asleep ? '睡着了 💤' : (myChar?.activity ?? '在校园里')}
            {state ? ` · 第${state.day}天 ${state.time_label}` : ''}
          </p>
        </div>
        {myChar && (
          <div className="w-24 shrink-0">
            <div className="h-1.5 overflow-hidden rounded-full bg-black/5">
              <div
                className="h-full rounded-full bg-green-500"
                style={{ width: `${Math.max(0, Math.min(100, myChar.energy ?? 0))}%` }}
              />
            </div>
            <p className="mt-1 text-right text-[10px] text-muted">
              精力 {Math.round(myChar.energy ?? 0)}
            </p>
          </div>
        )}
      </div>

      {/* 日期切换 */}
      <div className="scroll-thin mb-3 flex gap-1.5 overflow-x-auto pb-1">
        {days.map((d) => (
          <button
            key={d}
            type="button"
            className={[
              'shrink-0 rounded-full px-3 py-1 text-xs transition-colors',
              (day ?? today) === d ? 'bg-brand-500 text-white' : 'bg-black/5 text-muted hover:text-ink',
            ].join(' ')}
            onClick={() => setDay(d)}
          >
            第 {d} 天
          </button>
        ))}
      </div>

      {/* 心情曲线 */}
      <section className="card mb-4 p-4">
        <h3 className="mb-2 text-sm font-medium text-ink">心情起伏</h3>
        <MoodChart series={diary?.mood_series ?? []} />
      </section>

      {/* 反思卡 */}
      {(diary?.reflections ?? []).length > 0 && (
        <section className="mb-4 space-y-2">
          {(diary?.reflections ?? []).map((r, i) => (
            <div key={`${r.tick}-${i}`} className="rounded-card bg-ink p-4 text-white">
              <p className="mb-1 text-[10px] uppercase tracking-wide opacity-60">
                夜间反思 · {r.tick}
              </p>
              <p className="text-sm leading-relaxed">{r.text}</p>
            </div>
          ))}
        </section>
      )}

      {/* 时间线 */}
      <section className="card mb-4 p-4">
        <h3 className="mb-3 text-sm font-medium text-ink">这一天的轨迹</h3>
        <Timeline entries={diary?.entries ?? []} />
      </section>

      <WhisperBox />
    </div>
  );
}
