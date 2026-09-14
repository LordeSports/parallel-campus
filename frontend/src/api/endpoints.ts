/**
 * 按领域分组的接口封装。路径与 03-api.md 一一对应。
 * 响应类型来自 `types.ts`（由 OpenAPI 生成），此处只做别名收敛。
 */

import { http, qs } from './client';
import type {
  CharacterDetailView,
  CharacterSummaryView,
  ActiveEventView,
  AdminOverviewView,
  AdminSessionView,
  AdminWeatherRequest,
  ApiSettingsRequest,
  ApiSettingsView,
  CampusMapView,
  ClockRequest,
  CommentView,
  DiaryView,
  EventView,
  LocationView,
  MapSaveRequest,
  PersonaFile,
  PersonaResponse,
  PostDetailView,
  PostView,
  ReportView,
  ModeResponse,
  NpcRequest,
  NpcView,
  SceneRequest,
  SimulationRequest,
  UserView,
  WorldStateView,
} from './types';

export interface PostListPage {
  items: PostView[];
  next_cursor: string | null;
}

export type Board = 'wall' | 'tree_hole' | 'notice';

/** 我的分身：CharacterDetail + 耳语/投放元信息 */
export interface MyAvatar extends CharacterDetailView {
  whispers_left_today?: number;
  deployed_at_tick?: number;
  persona_version?: number;
}

// ── 认证 ──

/** OAuth 调试日志（仅 DEV_MODE 下由后端返回） */
export interface OauthLogEntry {
  at: string;
  event: string;
  [key: string]: unknown;
}

export interface OauthLogView {
  dev_mode: boolean;
  public_base_url: string;
  redirect_uri: string;
  cookie_secure: boolean;
  app_id_configured: boolean;
  app_key_configured: boolean;
  access_secret_configured: boolean;
  entries: OauthLogEntry[];
}

export const authApi = {
  me: () => http.get<UserView>('/api/auth/me'),
  logout: () => http.post<void>('/api/auth/logout'),
  devLogin: (name: string) => http.post<UserView>('/api/auth/dev-login', { name }),
  /** 仅在 DEV_MODE 下可用；其余情况返回 404 */
  oauthLog: () => http.get<OauthLogView>('/api/auth/oauth-log'),
  /** 级联删除账号（US-14） */
  destroy: () => http.del<void>('/api/auth/me'),
};

// ── 人格 ──

export const personaApi = {
  get: () => http.get<PersonaResponse>('/api/persona'),
  generate: (force = false) => http.post<PersonaResponse>(`/api/persona/generate${qs({ force })}`),
  save: (file: PersonaFile) => http.put<PersonaResponse>('/api/persona', { file }),
  deploy: (body: {
    display_name: string;
    avatar_key: string;
    appearance: string;
    major: string;
    grade: string;
    club: string | null;
  }, redeploy = false) =>
    http.post<CharacterDetailView>(`/api/persona/deploy${qs({ redeploy })}`, body),
};

// ── 世界 ──

export const worldApi = {
  state: () => http.get<WorldStateView>('/api/world/state'),
  locations: () => http.get<LocationView[]>('/api/world/locations'),
  /** 可编辑校园地图（等距手绘） */
  map: () => http.get<CampusMapView>('/api/world/map'),
  characters: () => http.get<CharacterSummaryView[]>('/api/world/characters'),
  character: (id: string) =>
    http.get<CharacterDetailView>(`/api/world/characters/${encodeURIComponent(id)}`),
  eventsSince: (sinceTick: number, limit = 200) =>
    http.get<EventView[]>(`/api/world/events${qs({ since_tick: sinceTick, limit })}`),
};

// ── 校园墙 ──

export const wallApi = {
  posts: (board: Board, cursor?: string | null, limit = 20) =>
    http.get<PostListPage>(`/api/wall/posts${qs({ board, cursor, limit })}`),
  post: (id: string) => http.get<PostDetailView>(`/api/wall/posts/${encodeURIComponent(id)}`),
  create: (text: string) => http.post<PostView>('/api/wall/posts', { board: 'tree_hole', text }),
  comment: (postId: string, text: string) =>
    http.post<CommentView>(`/api/wall/posts/${encodeURIComponent(postId)}/comments`, { text }),
  like: (postId: string) =>
    http.post<{ liked: boolean; like_count: number }>(
      `/api/wall/posts/${encodeURIComponent(postId)}/like`,
    ),
};

// ── 我的分身 ──

export const avatarApi = {
  me: () => http.get<MyAvatar>('/api/avatar'),
  diary: (day?: number) => http.get<DiaryView>(`/api/avatar/diary${qs({ day })}`),
  whisper: (text: string) =>
    http.post<{ whisper_id: string; whispers_left_today: number }>('/api/avatar/whisper', { text }),
  report: (day?: number) => http.get<ReportView>(`/api/avatar/report${qs({ day })}`),
};

// ── 健康 ──

export interface HealthView {
  status: string;
  version: string;
  tick: number;
  mode: string;
  dev_mode: boolean;
}

export const healthApi = {
  check: () => http.get<HealthView>('/api/health'),
};

export const adminApi = {
  session: () => http.get<AdminSessionView>('/api/admin/session'),
  login: (username: string, password: string) => http.post<AdminSessionView>('/api/admin/login', { username, password }),
  logout: () => http.post<void>('/api/admin/logout'),
  overview: () => http.get<AdminOverviewView>('/api/admin/overview'),
  simulation: (payload: SimulationRequest) => http.put<ModeResponse>('/api/admin/simulation', payload),
  clock: (payload: ClockRequest) => http.put<WorldStateView>('/api/admin/clock', payload),
  weather: (payload: AdminWeatherRequest) => http.put<WorldStateView>('/api/admin/weather', payload),
  locations: () => http.get<LocationView[]>('/api/admin/locations'),
  npcs: () => http.get<NpcView[]>('/api/admin/npcs'),
  createNpc: (payload: NpcRequest) => http.post<NpcView>('/api/admin/npcs', payload),
  updateNpc: (id: string, payload: NpcRequest) => http.put<NpcView>(`/api/admin/npcs/${id}`, payload),
  scenes: () => http.get<ActiveEventView[]>('/api/admin/scenes'),
  createScene: (payload: SceneRequest) => http.post<ActiveEventView>('/api/admin/scenes', payload),
  endScene: (id: string) => http.post<ActiveEventView>(`/api/admin/scenes/${id}/end`),
  /** 可编辑校园地图 */
  map: () => http.get<CampusMapView>('/api/admin/map'),
  saveMap: (payload: MapSaveRequest) => http.put<CampusMapView>('/api/admin/map', payload),
  settings: () => http.get<ApiSettingsView>('/api/admin/settings'),
  saveSettings: (payload: ApiSettingsRequest) => http.put<ApiSettingsView>('/api/admin/settings', payload),
};
