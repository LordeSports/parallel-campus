/** 我的分身（spec/07 §6）：详情 / 日记 / 耳语 / 匹配报告。 */

import { create } from 'zustand';

import { avatarApi, type MyAvatar } from '../api/endpoints';
import { sse, type SseEvent } from '../api/sse';
import type { DiaryView, ReportView } from '../api/types';

interface AvatarStore {
  me: MyAvatar | null;
  diary: DiaryView | null;
  report: ReportView | null;
  whispersLeft: number;
  loading: boolean;
  error: string | null;
  /** 今日已被回复的耳语（SSE 推回） */
  whisperReplies: { id: string; text: string; at: string }[];

  fetchMe: () => Promise<void>;
  fetchDiary: (day?: number) => Promise<void>;
  fetchReport: (day?: number) => Promise<void>;
  whisper: (text: string) => Promise<void>;
  applyEvent: (evt: SseEvent) => void;
  reset: () => void;
}

export const useAvatar = create<AvatarStore>((set, get) => ({
  me: null,
  diary: null,
  report: null,
  whispersLeft: 3,
  loading: false,
  error: null,
  whisperReplies: [],

  async fetchMe() {
    set({ loading: true, error: null });
    try {
      const me = await avatarApi.me();
      set({
        me,
        whispersLeft: me.whispers_left_today ?? get().whispersLeft,
        loading: false,
      });
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : '分身还不存在',
      });
    }
  },

  async fetchDiary(day) {
    try {
      const diary = await avatarApi.diary(day);
      set({ diary });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : '日记还没写好' });
    }
  },

  async fetchReport(day) {
    try {
      const report = await avatarApi.report(day);
      set({ report });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : '报告还没生成' });
    }
  },

  async whisper(text) {
    const r = await avatarApi.whisper(text);
    set({ whispersLeft: r.whispers_left_today });
    void sse;
  },

  applyEvent(evt) {
    const d = evt.data as Record<string, unknown>;
    if (evt.type === 'whisper_response') {
      const reply = String(d.text ?? d.reply ?? '');
      if (!reply) return;
      set({
        whisperReplies: [
          {
            id: String(d.whisper_id ?? d.id ?? `w-${Date.now()}`),
            text: reply,
            at: String(d.time_label ?? ''),
          },
          ...get().whisperReplies,
        ].slice(0, 20),
      });
      return;
    }
    if (evt.type === 'report_ready') {
      void get().fetchReport(Number(d.day ?? undefined) || undefined);
      return;
    }
    if (evt.type === 'reflection') {
      const mood = d.mood as MyAvatar['mood'] | undefined;
      const me = get().me;
      if (me && mood) set({ me: { ...me, mood } });
    }
  },

  reset() {
    set({
      me: null,
      diary: null,
      report: null,
      whisperReplies: [],
      loading: false,
      error: null,
    });
  },
}));
