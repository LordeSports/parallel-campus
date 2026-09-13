/** 匹配报告（spec/07 §3.6）。 */

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { avatarApi } from '../api/endpoints';
import type { ReportFriendView, ReportView } from '../api/types';
import RelationGraph from '../components/RelationGraph';
import { useSession } from '../store/session';
import { useWorld } from '../store/world';

function AffinityRing({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  const r = 18;
  const c = 2 * Math.PI * r;
  return (
    <svg width="46" height="46" viewBox="0 0 46 46" className="shrink-0">
      <circle cx="23" cy="23" r={r} fill="none" stroke="#00000012" strokeWidth="4" />
      <circle
        cx="23"
        cy="23"
        r={r}
        fill="none"
        stroke="#0084ff"
        strokeWidth="4"
        strokeLinecap="round"
        strokeDasharray={`${(pct / 100) * c} ${c}`}
        transform="rotate(-90 23 23)"
      />
      <text x="23" y="27" textAnchor="middle" fontSize="11" fill="#1a1a1a">
        {Math.round(value)}
      </text>
    </svg>
  );
}

function FriendCard({ friend }: { friend: ReportFriendView }) {
  const c = friend.character;
  return (
    <article className="card p-4">
      <header className="flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-full bg-black/5 text-lg">
          {c.kind === 'npc' ? '🎓' : '🙂'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-ink">{c.name}</span>
            {c.kind === 'npc' && (
              <span className="chip bg-black/5 px-1.5 py-0.5 text-[10px]">校园 NPC</span>
            )}
          </div>
          {c.archetype && <p className="truncate text-xs text-muted">{c.archetype}</p>}
        </div>
        <AffinityRing value={friend.affinity} />
      </header>

      <p className="mt-3 text-sm leading-relaxed text-ink">{friend.story}</p>

      {(friend.shared_topics ?? []).length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {(friend.shared_topics ?? []).map((t) => (
            <span key={t} className="chip bg-brand-50 px-2 py-0.5 text-[10px] text-brand-600">
              {t}
            </span>
          ))}
        </div>
      )}

      <footer className="mt-3 flex items-center justify-between border-t border-black/5 pt-2.5">
        <span className="text-xs text-muted">
          好感 {friend.affinity_delta >= 0 ? '+' : ''}
          {friend.affinity_delta}
        </span>
        {friend.is_human && friend.zhihu_url ? (
          <a
            href={friend.zhihu_url}
            target="_blank"
            rel="noopener"
            className="text-xs text-brand-600 hover:underline"
          >
            去知乎看看 TA →
          </a>
        ) : friend.is_human ? (
          <span className="text-xs text-muted">对方暂未公开主页</span>
        ) : (
          <span className="text-xs text-muted">校园里的老同学</span>
        )}
      </footer>
    </article>
  );
}

export default function Report() {
  const user = useSession((s) => s.user);
  const state = useWorld((s) => s.state);
  const [report, setReport] = useState<ReportView | null>(null);
  const [notReady, setNotReady] = useState(false);
  const [day, setDay] = useState<number | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!user?.character_id) return;
    let alive = true;
    setErr(null);
    setNotReady(false);
    avatarApi
      .report(day)
      .then((r) => {
        if (alive) setReport(r);
      })
      .catch((e) => {
        if (!alive) return;
        const status = (e as { status?: number }).status;
        if (status === 404) setNotReady(true);
        else setErr(e instanceof Error ? e.message : '加载失败');
      });
    return () => {
      alive = false;
    };
  }, [day, user?.character_id]);

  if (!user?.character_id) {
    return (
      <div className="mx-auto max-w-xl px-3 py-16 text-center">
        <div className="card p-8">
          <p className="text-3xl">📊</p>
          <h2 className="mt-3 text-base font-medium text-ink">还没有可看的报告</h2>
          <p className="mt-1.5 text-sm text-muted">投放分身之后，每晚 23:30 会生成一份</p>
          <Link to="/persona" className="btn-primary mt-5 inline-flex">
            去投放分身
          </Link>
        </div>
      </div>
    );
  }

  const today = state?.day ?? 1;

  return (
    <div className="mx-auto max-w-2xl px-3 py-4">
      {/* 日期选择 */}
      <div className="scroll-thin mb-3 flex gap-1.5 overflow-x-auto pb-1">
        {Array.from({ length: Math.max(1, today) }, (_, i) => i + 1).map((d) => (
          <button
            key={d}
            type="button"
            className={[
              'shrink-0 rounded-full px-3 py-1 text-xs transition-colors',
              (day ?? today) === d
                ? 'bg-brand-500 text-white'
                : 'bg-black/5 text-muted hover:text-ink',
            ].join(' ')}
            onClick={() => setDay(d)}
          >
            第 {d} 天
          </button>
        ))}
      </div>

      {err && (
        <div className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>
      )}

      {notReady && (
        <div className="card p-8 text-center">
          <p className="text-sm text-muted">
            今晚 23:30 生成{state ? `（当前第${state.day}天 ${state.time_label}）` : ''}
          </p>
          <p className="mt-1 text-xs text-muted">分身还在校园里认识新朋友</p>
        </div>
      )}

      {report && (
        <div className="space-y-4">
          <section className="card p-5">
            <p className="mb-1 text-[11px] uppercase tracking-wide text-muted">
              第 {report.day} 天的你
            </p>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
              {report.summary}
            </p>
          </section>

          {(report.top_friends ?? []).length > 0 && (
            <>
              <h2 className="px-1 text-sm font-medium text-ink">最想再见到的人</h2>
              <div className="space-y-3">
                {(report.top_friends ?? []).slice(0, 3).map((f) => (
                  <FriendCard key={f.character.id} friend={f} />
                ))}
              </div>
            </>
          )}

          <RelationGraph friends={report.top_friends ?? []} />

          <div className="h-4" />
        </div>
      )}
    </div>
  );
}
