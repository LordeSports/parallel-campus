/** 校园墙（spec/07 §5）：三个板块分页 + 发帖/评论/点赞。 */

import { create } from 'zustand';

import { wallApi, type Board } from '../api/endpoints';
import type { CommentView, PostView } from '../api/types';

interface WallStore {
  board: Board;
  items: PostView[];
  cursor: string | null;
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  /** 正在展开详情的帖子 */
  detail: Record<string, { comments: CommentView[]; loading: boolean }>;

  setBoard: (b: Board) => void;
  load: (reset?: boolean) => Promise<void>;
  loadMore: () => Promise<void>;
  create: (text: string) => Promise<void>;
  submitComment: (postId: string, text: string) => Promise<void>;
  toggleLike: (postId: string) => Promise<void>;
  loadComments: (postId: string) => Promise<void>;
  patchPost: (id: string, patch: Partial<PostView>) => void;
}

const PAGE = 20;

export const useWall = create<WallStore>((set, get) => ({
  board: 'wall',
  items: [],
  cursor: null,
  loading: false,
  loadingMore: false,
  error: null,
  detail: {},

  setBoard(b) {
    if (get().board === b) return;
    set({ board: b, items: [], cursor: null, detail: {} });
    void get().load(true);
  },

  async load(reset = false) {
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const page = await wallApi.posts(get().board, null, PAGE);
      set({
        items: page.items,
        cursor: page.next_cursor,
        loading: false,
      });
      void reset;
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : '校园墙暂时刷不出来',
      });
    }
  },

  async loadMore() {
    const { cursor, loadingMore, loading, board, items } = get();
    if (!cursor || loadingMore || loading) return;
    set({ loadingMore: true });
    try {
      const page = await wallApi.posts(board, cursor, PAGE);
      const seen = new Set(items.map((p) => p.id));
      const merged = [...items, ...page.items.filter((p) => !seen.has(p.id))];
      set({ items: merged, cursor: page.next_cursor, loadingMore: false });
    } catch (err) {
      set({
        loadingMore: false,
        error: err instanceof Error ? err.message : '加载失败',
      });
    }
  },

  async create(text) {
    const post = await wallApi.create(text);
    const board = get().board;
    // 只有树洞板块才直接入列（发帖固定落树洞）
    if (board === 'tree_hole' || board === 'wall') {
      set({ items: [post, ...get().items] });
    }
  },

  async loadComments(postId) {
    const cur = get().detail[postId];
    if (cur?.loading) return;
    set({
      detail: { ...get().detail, [postId]: { comments: cur?.comments ?? [], loading: true } },
    });
    try {
      const full = await wallApi.post(postId);
      set({
        detail: {
          ...get().detail,
          [postId]: { comments: full.comments ?? [], loading: false },
        },
      });
      get().patchPost(postId, {
        comment_count: full.post.comment_count,
        like_count: full.post.like_count,
        liked_by_me: full.post.liked_by_me,
      });
    } catch {
      set({
        detail: { ...get().detail, [postId]: { comments: cur?.comments ?? [], loading: false } },
      });
    }
  },

  async submitComment(postId, text) {
    const c = await wallApi.comment(postId, text);
    const cur = get().detail[postId]?.comments ?? [];
    set({ detail: { ...get().detail, [postId]: { comments: [...cur, c], loading: false } } });
    const post = get().items.find((p) => p.id === postId);
    if (post) get().patchPost(postId, { comment_count: (post.comment_count ?? 0) + 1 });
  },

  async toggleLike(postId) {
    const r = await wallApi.like(postId);
    get().patchPost(postId, { liked_by_me: r.liked, like_count: r.like_count });
  },

  patchPost(id, patch) {
    set({ items: get().items.map((p) => (p.id === id ? { ...p, ...patch } : p)) });
  },
}));
