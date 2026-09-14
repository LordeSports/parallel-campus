/**
 * 校园地图 store。
 *
 * - `map` 始终是**服务端最新**的一份（玩家端与编辑器都以它为初始值）
 * - 管理员保存后后端广播 `map_updated` → `refreshIfStale()` 重新拉取
 * - 编辑中的草稿由 `MapEditor` 自己维护，避免污染玩家端视角
 */

import { create } from 'zustand';

import { worldApi } from '../api/endpoints';
import type { CampusMapView } from '../api/types';

interface MapStore {
  map: CampusMapView | null;
  loading: boolean;
  error: string | null;
  /** 最近一次成功拉取的版本号，用于 SSE 失效判断 */
  loadedVersion: number;

  fetch: () => Promise<void>;
  /** 收到 map_updated：版本更新则重拉 */
  refreshIfStale: (version: number) => void;
  /** 保存成功后把服务端返回的最新图直接写入（省一次往返） */
  setMap: (map: CampusMapView) => void;
}

export const useMap = create<MapStore>((set, get) => ({
  map: null,
  loading: false,
  error: null,
  loadedVersion: -1,

  async fetch() {
    if (get().loading) return;
    set({ loading: true, error: null });
    try {
      const map = await worldApi.map();
      set({ map, loading: false, loadedVersion: map.version });
    } catch (err) {
      set({ loading: false, error: err instanceof Error ? err.message : '地图加载失败' });
    }
  },

  refreshIfStale(version) {
    if (version > get().loadedVersion) void get().fetch();
  },

  setMap(map) {
    set({ map, loadedVersion: map.version, error: null });
  },
}));
