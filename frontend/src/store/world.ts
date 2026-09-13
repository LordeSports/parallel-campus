/** 世界状态（spec/07 §4）：地图 / 角色 / LiveFeed / 对话。 */

import { create } from 'zustand';

import { worldApi } from '../api/endpoints';
import { isKnownEvent, type SseEvent } from '../api/sse';
import type {
  ActiveEventView,
  BriefingView,
  CharacterSummaryView,
  LocationView,
  WeatherView,
  WorldStateView,
} from '../api/types';

/** 天气展示（spec/07 §2）：kind → emoji。 */
export const WEATHER_EMOJI: Record<string, string> = {
  sunny: '☀️',
  cloudy: '⛅',
  rainy: '🌧',
  foggy: '🌫',
  windy: '💨',
};

export function weatherLabel(w?: WeatherView | null): string {
  if (!w) return '—';
  const emoji = WEATHER_EMOJI[w.kind ?? ''] ?? '🌤';
  return `${emoji} ${w.temp_c ?? '--'}° ${w.text ?? ''}`.trim();
}

export interface FeedItem {
  key: string;
  tick: number;
  timeLabel: string;
  icon: string;
  text: string;
  /** 对话类条目可展开 */
  dialogueId?: string;
  characterId?: string;
}

export interface LiveDialogue {
  id: string;
  aId: string;
  bId: string;
  locationId: string;
  turns: { index: number; speakerId: string; text: string }[];
  ended: boolean;
  endedBecause?: string;
  /** 是否已展开 */
  open: boolean;
}

interface WorldStore {
  state: WorldStateView | null;
  locations: LocationView[];
  characters: Record<string, CharacterSummaryView>;
  feed: FeedItem[];
  dialogues: Record<string, LiveDialogue>;
  lastTick: number;
  connected: boolean;
  loading: boolean;
  error: string | null;
  /** 昨日简报（顶栏折叠卡） */
  briefing: BriefingView | null;

  bootstrap: () => Promise<void>;
  applyEvent: (evt: SseEvent) => void;
  setConnected: (v: boolean) => void;
  patchCharacter: (id: string, patch: Partial<CharacterSummaryView>) => void;
  upsertCharacter: (c: CharacterSummaryView) => void;
  clearFeed: () => void;
}

const FEED_MAX = 50;
const TURN_TAIL = 40;

function label(tick: number, day?: number): string {
  if (!day) return `#${tick}`;
  const m = ((tick - (day - 1) * 48) % 48) * 30 + 360;
  const hh = String(Math.floor(m / 60)).padStart(2, '0');
  const mm = String(m % 60).padStart(2, '0');
  return `第${day}天 ${hh}:${mm}`;
}

function pushFeed(feed: FeedItem[], item: FeedItem): FeedItem[] {
  return [item, ...feed].slice(0, FEED_MAX);
}

export const useWorld = create<WorldStore>((set, get) => ({
  state: null,
  locations: [],
  characters: {},
  feed: [],
  dialogues: {},
  lastTick: 0,
  connected: false,
  loading: false,
  error: null,
  briefing: null,

  async bootstrap() {
    set({ loading: true, error: null });
    try {
      const [state, locations, characters] = await Promise.all([
        worldApi.state(),
        worldApi.locations(),
        worldApi.characters(),
      ]);
      const map: Record<string, CharacterSummaryView> = {};
      for (const c of characters) map[c.id] = c;

      const since = Math.max(0, (state.tick ?? 0) - 6);
      let events: Awaited<ReturnType<typeof worldApi.eventsSince>> = [];
      try {
        events = await worldApi.eventsSince(since);
      } catch {
        /* 回放失败不阻塞首屏 */
      }

      set({
        state,
        locations,
        characters: map,
        loading: false,
        lastTick: Math.max(state.tick ?? 0, get().lastTick),
        briefing: (state as { briefing?: BriefingView | null }).briefing ?? null,
      });

      // 用回放事件重建近况（只入 feed，不重复写状态）
      for (const ev of events) {
        const type = String((ev as { kind?: string }).kind ?? '');
        if (!isKnownEvent(type)) continue;
      }
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : '校园暂时打不开，稍后再试',
      });
    }
  },

  applyEvent(evt) {
    const d = evt.data as Record<string, unknown>;
    const tick = Number(d.tick ?? get().lastTick);

    switch (evt.type) {
      case 'hello': {
        set({ lastTick: Math.max(get().lastTick, Number(d.tick ?? 0)) });
        return;
      }
      case 'tick': {
        const st = get().state;
        set({
          lastTick: Math.max(get().lastTick, Number(d.tick ?? 0)),
          state: st
            ? {
                ...st,
                tick: Number(d.tick ?? st.tick),
                day: Number(d.day ?? st.day),
                minute_of_day: Number(d.minute_of_day ?? st.minute_of_day),
                time_label: String(d.time_label ?? st.time_label),
                speed_mode: String(d.speed_mode ?? st.speed_mode),
                tick_seconds: Number(d.tick_seconds ?? st.tick_seconds),
              }
            : st,
        });
        return;
      }
      case 'weather': {
        const st = get().state;
        if (!st || !d.weather) return;
        set({ state: { ...st, weather: d.weather as WeatherView } });
        return;
      }      case 'event_started': {
        const st = get().state;
        const ev = d.event as ActiveEventView | undefined;
        if (!st || !ev) return;
        const rest = (st.active_events ?? []).filter((e) => e.id !== ev.id);
        set({ state: { ...st, active_events: [...rest, ev] } });
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-started-${ev.id}`,
            tick,
            timeLabel: label(tick, st.day),
            icon: '📣',
            text: `事件开始：${ev.title}`,
          }),
        });
        return;
      }
      case 'event_ended': {
        const st = get().state;
        const ev = d.event as ActiveEventView | undefined;
        if (!st || !ev) return;
        set({
          state: {
            ...st,
            active_events: (st.active_events ?? []).filter((e) => e.id !== ev.id),
          },
        });
        return;
      }
      case 'character_moved': {
        const id = String(d.character_id ?? '');
        const to = String(d.to ?? '');
        const from = String(d.from ?? '');
        const c = get().characters[id];
        if (c) {
          get().patchCharacter(id, {
            location_id: to as CharacterSummaryView['location_id'],
            activity: (d.activity as string | undefined) ?? c.activity,
          });
        }
        const name = c?.name ?? id;
        const fromName = get().locations.find((l) => l.id === from)?.name ?? from;
        const toName = get().locations.find((l) => l.id === to)?.name ?? to;
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-mv-${id}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '🚶',
            text: `${name} 从${fromName}去了${toName}`,
          }),
        });
        return;
      }
      case 'character_activity': {
        const id = String(d.character_id ?? '');
        get().patchCharacter(id, {
          activity: typeof d.activity === 'string' ? d.activity : undefined,
          mood: (d.mood as CharacterSummaryView['mood']) ?? undefined,
        });
        return;
      }
      case 'dialogue_started': {
        const id = String(d.dialogue_id ?? '');
        const aId = String(d.a_id ?? '');
        const bId = String(d.b_id ?? '');
        const loc = String(d.location_id ?? '');
        set({
          dialogues: {
            ...get().dialogues,
            [id]: { id, aId, bId, locationId: loc, turns: [], ended: false, open: false },
          },
        });
        const an = get().characters[aId]?.name ?? aId;
        const bn = get().characters[bId]?.name ?? bId;
        const ln = get().locations.find((l) => l.id === loc)?.name ?? loc;
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-ds-${id}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '💬',
            text: `${an} ↔ ${bn} 开始聊天 @${ln}`,
            dialogueId: id,
          }),
        });
        return;
      }
      case 'dialogue_turn': {
        const id = String(d.dialogue_id ?? '');
        const cur = get().dialogues[id];
        if (!cur) return;
        const turns = [
          ...cur.turns,
          {
            index: Number(d.index ?? cur.turns.length),
            speakerId: String(d.speaker_id ?? ''),
            text: String(d.text ?? ''),
          },
        ].slice(-TURN_TAIL);
        set({ dialogues: { ...get().dialogues, [id]: { ...cur, turns } } });
        return;
      }
      case 'dialogue_ended': {
        const id = String(d.dialogue_id ?? '');
        const cur = get().dialogues[id];
        if (cur) {
          set({
            dialogues: {
              ...get().dialogues,
              [id]: { ...cur, ended: true, endedBecause: String(d.ended_because ?? '') },
            },
          });
        }
        const aId = String(d.a_id ?? cur?.aId ?? '');
        const bId = String(d.b_id ?? cur?.bId ?? '');
        const an = get().characters[aId]?.name ?? aId;
        const bn = get().characters[bId]?.name ?? bId;
        const da = Number(d.a_to_b_delta ?? 0);
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-de-${id}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '🤝',
            text: `${an} 和 ${bn} 聊完了（好感 ${da >= 0 ? '+' : ''}${da}）`,
            dialogueId: id,
          }),
        });
        return;
      }
      case 'post_created': {
        const p = d.post as { author?: { name?: string } | null; text?: string } | undefined;
        if (!p) return;
        const who = p.author?.name ?? '围观者';
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-pc-${(p as { id?: string }).id ?? tick}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '📝',
            text: `${who} 发帖：${String(p.text ?? '').slice(0, 40)}`,
          }),
        });
        return;
      }
      case 'comment_created': {
        const c = d.comment as { author?: { name?: string } | null; text?: string } | undefined;
        if (!c) return;
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-cc-${tick}-${Math.random().toString(36).slice(2, 7)}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '💭',
            text: `${c.author?.name ?? '围观者'} 评论：${String(c.text ?? '').slice(0, 30)}`,
          }),
        });
        return;
      }
      case 'like_created': {
        const pid = String(d.post_id ?? '');
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-lk-${pid}-${Number(d.like_count ?? 0)}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '👍',
            text: `有人点赞了动态（共 ${d.like_count ?? 0} 赞）`,
          }),
        });
        return;
      }
      case 'dm_sent': {
        const from = get().characters[String(d.from_id ?? '')]?.name ?? String(d.from_id ?? '');
        const to = get().characters[String(d.to_id ?? '')]?.name ?? String(d.to_id ?? '');
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-dm-${from}-${to}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '💌',
            text: `${from} 给 ${to} 发了私信`,
          }),
        });
        return;
      }
      case 'whisper_response':
      case 'reflection':
        // 与「我的分身」相关，交给 avatar store 过滤展示
        return;
      case 'briefing': {
        set({ briefing: { day: Number(d.day ?? 0), text: String(d.text ?? '') } });
        return;
      }
      case 'report_ready': {
        set({
          feed: pushFeed(get().feed, {
            key: `${evt.id}-rr-${d.character_id ?? ''}-${d.day ?? ''}`,
            tick,
            timeLabel: label(tick, get().state?.day),
            icon: '📊',
            text: `第 ${d.day ?? '?'} 天的匹配报告已生成`,
          }),
        });
        return;
      }
      case 'degraded': {
        const st = get().state;
        if (!st) return;
        set({ state: { ...st, degraded: Boolean(d.degraded) } });
        return;
      }
      default:
        console.debug('[world] 未知事件类型，已忽略', evt.type);
    }
  },

  setConnected(v) {
    set({ connected: v });
  },

  patchCharacter(id, patch) {
    const cur = get().characters[id];
    if (!cur) return;
    set({ characters: { ...get().characters, [id]: { ...cur, ...patch } } });
  },

  upsertCharacter(c) {
    set({ characters: { ...get().characters, [c.id]: c } });
  },

  clearFeed() {
    set({ feed: [] });
  },
}));

/** 心情表情（spec/07 §7）。 */
export function moodEmoji(valence?: number | null, arousal?: number | null): string {
  const v = valence ?? 0;
  let face = '😐';
  if (v > 0.4) face = '😄';
  else if (v > 0.1) face = '🙂';
  else if (v > -0.1) face = '😐';
  else if (v > -0.4) face = '😕';
  else face = '😞';
  return (arousal ?? 0) > 0.6 ? `${face}⚡` : face;
}

/** 速度模式徽标（spec/07 §2）。 */
export const SPEED_BADGE: Record<string, { dot: string; text: string }> = {
  online: { dot: 'bg-brand-500', text: '实时' },
  idle: { dot: 'bg-muted', text: '慢速' },
  fast_forward: { dot: 'bg-blue-500', text: '快进' },
  paused: { dot: 'bg-amber-500', text: '暂停' },
};
