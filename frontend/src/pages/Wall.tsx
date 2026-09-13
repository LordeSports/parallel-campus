/** 校园墙（spec/07 §3.4）。 */

import { useEffect, useRef, useState } from 'react';

import { ApiError } from '../api/client';
import type { Board } from '../api/endpoints';
import type { PostView } from '../api/types';
import { useWall } from '../store/wall';
import { moodEmoji } from '../store/world';
import Toast from '../components/Toast';

const BOARDS: { id: Board; label: string }[] = [
  { id: 'wall', label: '校园墙' },
  { id: 'tree_hole', label: '树洞' },
  { id: 'notice', label: '公告' },
];

const KIND_BADGE: Record<string, { text: string; cls: string }> = {
  player: { text: '分身', cls: 'bg-brand-50 text-brand-600' },
  npc: { text: '校园 NPC', cls: 'bg-black/5 text-muted' },
  system: { text: '校园广播', cls: 'bg-amber-50 text-amber-700' },
};

function PostCard({ post }: { post: PostView }) {
  const submitComment = useWall((s) => s.submitComment);
  const loadComments = useWall((s) => s.loadComments);
  const toggleLike = useWall((s) => s.toggleLike);
  const comments = useWall((s) => s.detail[post.id]?.comments ?? []);

  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  const badge = post.author ? KIND_BADGE[post.author.kind] : undefined;

  return (
    <article className="card p-4">
      <header className="flex items-center gap-2.5">
        <div className="grid h-9 w-9 place-items-center rounded-full bg-black/5 text-sm">
          {moodEmoji()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-ink">
              {post.author?.name ?? post.author_label ?? '匿名'}
            </span>
            {badge && (
              <span className={`chip px-1.5 py-0.5 text-[10px] ${badge.cls}`}>{badge.text}</span>
            )}
          </div>
          <span className="text-xs text-muted">{post.time_label ?? `#${post.tick}`}</span>
        </div>
      </header>

      <p className="mt-2.5 whitespace-pre-wrap text-sm leading-relaxed text-ink">{post.text}</p>

      {post.source && (
        <a
          href={post.source.url}
          target="_blank"
          rel="noopener"
          className="mt-2 inline-block text-xs text-brand-600 hover:underline"
        >
          来源：知乎 · {post.source.title}
        </a>
      )}

      <footer className="mt-3 flex items-center gap-4 border-t border-black/5 pt-2.5 text-xs text-muted">
        <button
          type="button"
          className={post.liked_by_me ? 'text-brand-600' : 'hover:text-ink'}
          onClick={() => {
            void toggleLike(post.id);
          }}
        >
          👍 {post.like_count ?? 0}
        </button>
        <button
          type="button"
          className="hover:text-ink"
          onClick={() => {
            const next = !open;
            setOpen(next);
            if (next) void loadComments(post.id);
          }}
        >
          💬 {post.comment_count ?? 0}
        </button>
      </footer>

      {open && (
        <div className="mt-2.5 space-y-2 border-t border-black/5 pt-2.5">
          {comments.length === 0 && <p className="text-xs text-muted">还没有人说话</p>}
          {comments.map((c) => (
            <div key={c.id} className="text-xs">
              <span className="mr-1.5 font-medium text-ink">
                {c.author?.name ?? c.author_label ?? '围观者'}
              </span>
              <span className="text-ink">{c.text}</span>
            </div>
          ))}

          <form
            className="flex gap-2 pt-1"
            onSubmit={(e) => {
              e.preventDefault();
              if (!text.trim()) return;
              setBusy(true);
              submitComment(post.id, text.trim())
                .then(() => setText(''))
                .catch(() => undefined)
                .finally(() => setBusy(false));
            }}
          >
            <input
              className="min-w-0 flex-1 rounded-full border border-black/10 px-3 py-1.5 text-xs outline-none focus:border-brand-500"
              placeholder="说点什么…（≤200 字）"
              maxLength={200}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button type="submit" className="btn-primary px-3 py-1.5 text-xs" disabled={busy}>
              发送
            </button>
          </form>
        </div>
      )}
    </article>
  );
}

export default function Wall() {
  const board = useWall((s) => s.board);
  const items = useWall((s) => s.items);
  const loading = useWall((s) => s.loading);
  const loadingMore = useWall((s) => s.loadingMore);
  const cursor = useWall((s) => s.cursor);
  const error = useWall((s) => s.error);
  const setBoard = useWall((s) => s.setBoard);
  const load = useWall((s) => s.load);
  const loadMore = useWall((s) => s.loadMore);
  const create = useWall((s) => s.create);

  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void load(true);
  }, [board, load]);

  // 无限滚动
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting) void loadMore();
    });
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore, cursor]);

  return (
    <div className="mx-auto max-w-2xl px-3 py-4">
      {/* 板块 Tab */}
      <div className="mb-4 flex gap-1 rounded-full bg-black/5 p-1">
        {BOARDS.map((b) => (
          <button
            key={b.id}
            type="button"
            className={[
              'flex-1 rounded-full py-1.5 text-sm transition-colors',
              board === b.id ? 'bg-white font-medium text-ink shadow-sm' : 'text-muted',
            ].join(' ')}
            onClick={() => setBoard(b.id)}
          >
            {b.label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>
      )}

      {/* 树洞发帖（spec/07 §3.4） */}
      {board === 'tree_hole' && (
        <form
          className="card mb-4 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!text.trim()) return;
            setBusy(true);
            create(text.trim())
              .then(() => setText(''))
              .catch((err) => {
                if (err instanceof ApiError && err.status === 429) {
                  setToast(`发得太快了，${err.retryAfter ?? 30}s 后再试`);
                } else {
                  setToast(err instanceof Error ? err.message : '发帖失败');
                }
              })
              .finally(() => setBusy(false));
          }}
        >
          <textarea
            className="w-full resize-none rounded-xl border border-black/10 p-3 text-sm outline-none focus:border-brand-500"
            rows={3}
            maxLength={500}
            placeholder="把心事丢进树洞…（≤500 字，署名「围观者」）"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-muted">{text.length}/500</span>
            <button type="submit" className="btn-primary px-4 py-1.5 text-xs" disabled={busy}>
              {busy ? '发送中…' : '丢进去'}
            </button>
          </div>
        </form>
      )}

      {/* 列表 */}
      {loading && items.length === 0 && (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card space-y-2.5 p-4">
              <div className="flex items-center gap-2.5">
                <div className="skeleton h-9 w-9 rounded-full" />
                <div className="skeleton h-3 w-24" />
              </div>
              <div className="skeleton h-3 w-full" />
              <div className="skeleton h-3 w-2/3" />
            </div>
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="card px-4 py-12 text-center">
          <p className="text-sm text-muted">这面墙还空着</p>
          {board === 'tree_hole' && (
            <p className="mt-1 text-xs text-muted">说点什么，让校园听到你</p>
          )}
        </div>
      )}

      <div className="space-y-3">
        {items.map((p) => (
          <PostCard key={p.id} post={p} />
        ))}
      </div>

      <div ref={sentinel} className="h-10" />
      {loadingMore && <p className="pb-4 text-center text-xs text-muted">正在加载更多…</p>}
      {!cursor && items.length > 0 && (
        <p className="pb-4 text-center text-xs text-muted">到底了</p>
      )}

      {toast && <Toast text={toast} onClose={() => setToast(null)} />}
    </div>
  );
}
