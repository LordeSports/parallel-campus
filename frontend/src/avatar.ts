/**
 * 头像体系——与后端 `app/seeds/avatars.json` 保持一致。
 *
 * 约定：**前端只提交 `av_XX` 这类 key**，emoji 与底色只用于展示。
 *
 * 之前 DeployForm 直接把 emoji 字符（🌱🌊…）当作 `avatar_key` 提交，
 * 与后端的 `av_XX` 体系对不上：后端 `get_avatar('🌱')` 查不到，只能回落成默认脸。
 * 更麻烦的是 emoji 依赖字体，缺字形时整排头像会变成空框 / 问号。
 *
 * 现在统一走 key + 兜底映射：任何未知 key（含历史遗留的 emoji 值）都会稳定映射到
 * 某个头像，**永远不会渲染出问号**。
 */

export interface AvatarMeta {
  key: string;
  emoji: string;
  bg: string;
}

export const AVATARS: AvatarMeta[] = [
  { key: 'av_01', emoji: '🧑‍💻', bg: '#dbeafe' },
  { key: 'av_02', emoji: '🧑‍🎨', bg: '#fee2e2' },
  { key: 'av_03', emoji: '🧑‍🔬', bg: '#dcfce7' },
  { key: 'av_04', emoji: '🧑‍🎓', bg: '#fef3c7' },
  { key: 'av_05', emoji: '🧑‍🏫', bg: '#ede9fe' },
  { key: 'av_06', emoji: '🧑‍🍳', bg: '#fce7f3' },
  { key: 'av_07', emoji: '🧑‍🚀', bg: '#e0f2fe' },
  { key: 'av_08', emoji: '🧑‍🔧', bg: '#ffedd5' },
  { key: 'av_09', emoji: '🦊', bg: '#e7e5e4' },
  { key: 'av_10', emoji: '🐼', bg: '#e5e7eb' },
  { key: 'av_11', emoji: '🐧', bg: '#d1fae5' },
  { key: 'av_12', emoji: '🐱', bg: '#fef9c3' },
  { key: 'av_13', emoji: '🦉', bg: '#ecfccb' },
  { key: 'av_14', emoji: '🐺', bg: '#ccfbf1' },
  { key: 'av_15', emoji: '🌵', bg: '#f3e8ff' },
  { key: 'av_16', emoji: '🎧', bg: '#ffe4e6' },
  { key: 'av_17', emoji: '📷', bg: '#e0e7ff' },
  { key: 'av_18', emoji: '🎮', bg: '#f0fdf4' },
  { key: 'av_19', emoji: '🍥', bg: '#fff7ed' },
  { key: 'av_20', emoji: '🌙', bg: '#f5f3ff' },
  { key: 'av_21', emoji: '🎸', bg: '#fef2f2' },
  { key: 'av_22', emoji: '🧩', bg: '#f0f9ff' },
  { key: 'av_23', emoji: '🛰️', bg: '#f7fee7' },
  { key: 'av_24', emoji: '🪴', bg: '#fdf4ff' },
];

/** 可选的用户头像（不含系统 / 特殊账号）。 */
export const AVATAR_KEYS: string[] = AVATARS.map((a) => a.key);

const BY_KEY = new Map(AVATARS.map((a) => [a.key, a]));

/** 系统广播头像。 */
export const SYSTEM_AVATAR: AvatarMeta = { key: 'av_sys', emoji: '📣', bg: '#9ca3af' };

function hashText(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

/**
 * 取头像元信息。未知 / 空 key 时按 `seedText` 稳定兜底——
 * 保证同一个角色每次渲染都是同一张脸，且**绝不会出现问号**。
 */
export function avatarMeta(key: string | null | undefined, seedText = ''): AvatarMeta {
  if (key === SYSTEM_AVATAR.key) return SYSTEM_AVATAR;
  const found = key ? BY_KEY.get(key) : undefined;
  if (found) return found;
  return AVATARS[hashText(`${key ?? ''}|${seedText}`) % AVATARS.length];
}
