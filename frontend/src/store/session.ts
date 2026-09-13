/** 会话状态（spec/07 §4）。 */

import { create } from 'zustand';

import { authApi } from '../api/endpoints';
import { ApiError } from '../api/client';
import type { UserView } from '../api/types';

interface SessionState {
  user: UserView | null;
  loading: boolean;
  /** 已尝试过 fetchMe；用于路由守卫避免闪烁 */
  ready: boolean;
  error: string | null;
  fetchMe: () => Promise<UserView | null>;
  setUser: (user: UserView | null) => void;
  logout: () => Promise<void>;
  destroy: () => Promise<void>;
}

export const useSession = create<SessionState>((set) => ({
  user: null,
  loading: false,
  ready: false,
  error: null,

  async fetchMe() {
    set({ loading: true, error: null });
    try {
      const user = await authApi.me();
      set({ user, loading: false, ready: true });
      return user;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        set({ user: null, loading: false, ready: true });
        return null;
      }
      set({
        user: null,
        loading: false,
        ready: true,
        error: err instanceof Error ? err.message : '加载失败',
      });
      return null;
    }
  },

  setUser(user) {
    set({ user, ready: true });
  },

  async logout() {
    try {
      await authApi.logout();
    } catch {
      /* 忽略：本地状态优先 */
    }
    set({ user: null });
  },

  async destroy() {
    await authApi.destroy();
    set({ user: null });
  },
}));

/** 登录后的落点（spec/07 §1）。 */
export function landingPath(user: UserView | null): string {
  if (!user) return '/login';
  if (!user.has_persona) return '/persona';
  if (!user.character_id) return '/persona';
  return '/campus';
}
