/**
 * SSE 客户端（spec/07 §5）。
 *
 * - 同源 `EventSource('/api/stream')`，带 cookie
 * - 监听 03 §7 全部事件类型 → 交给 `applyEvent` 分发
 * - `onerror` → `connected=false` → 指数退避重连（1s→2s→4s…≤30s）
 * - 重连前先 `GET /world/events?since_tick=lastTick` 回放，避免漏事件
 * - 页面隐藏 > 5 分钟 → 关闭连接（少算一个观众）；可见时重开
 * - 单例：多次 `connect()` 只保留一条连接
 */

export const SSE_EVENT_TYPES = [
  'hello',
  'heartbeat',
  'tick',
  'weather',
  'event_started',
  'event_ended',
  'character_moved',
  'character_activity',
  'dialogue_started',
  'dialogue_turn',
  'dialogue_ended',
  'post_created',
  'comment_created',
  'like_created',
  'dm_sent',
  'whisper_response',
  'reflection',
  'briefing',
  'report_ready',
  'degraded',
] as const;

export type SseEventType = (typeof SSE_EVENT_TYPES)[number];

export interface SseEvent {
  /** 事件 id（后端递增 tick）；`hello`/`heartbeat` 可能为空 */
  id: string;
  type: string;
  /** 已解析的 payload；解析失败时为 {} */
  data: Record<string, unknown>;
  /** 客户端接收时刻（ms），用于 LiveFeed 排序兜底 */
  receivedAt: number;
}

export interface SseHandlers {
  onEvent: (evt: SseEvent) => void;
  onConnected?: (connected: boolean) => void;
  /** 重连前回放用：返回当前已收到的最大 tick */
  getLastTick?: () => number;
  /** 回放接口返回的事件，逐条交给 onEvent */
  replay?: (sinceTick: number) => Promise<void>;
}

const KNOWN = new Set<string>(SSE_EVENT_TYPES);
const HIDDEN_CLOSE_MS = 5 * 60 * 1000;
const BACKOFF_START = 1000;
const BACKOFF_MAX = 30_000;

/** 供 applyEvent 的未知类型日志使用。 */
export function isKnownEvent(type: string): boolean {
  return KNOWN.has(type);
}

export class SseClient {
  private es: EventSource | null = null;
  private handlers: SseHandlers | null = null;
  private backoff = BACKOFF_START;
  private timer: number | null = null;
  private hiddenSince: number | null = null;
  private started = false;

  /** 建立连接；重复调用是空操作。 */
  start(handlers: SseHandlers): void {
    if (this.started) {
      this.handlers = handlers;
      if (!this.es) this.open();
      return;
    }
    this.started = true;
    this.handlers = handlers;
    this.installVisibility();

    // 首次连接前先回放一次（覆盖「上次关页 → 现在重开」的空档）
    const lastTick = handlers.getLastTick?.() ?? 0;
    if (lastTick > 0 && handlers.replay) {
      void handlers.replay(lastTick).finally(() => this.open());
    } else {
      this.open();
    }
  }

  stop(): void {
    this.started = false;
    this.clearTimer();
    this.close();
  }

  get connected(): boolean {
    return this.es !== null && this.es.readyState === EventSource.OPEN;
  }

  // ── 内部 ──

  private open(): void {
    if (!this.started || this.es) return;
    const h = this.handlers;
    if (!h) return;

    const es = new EventSource('/api/stream', { withCredentials: true });
    this.es = es;

    es.onopen = () => {
      this.backoff = BACKOFF_START;
      h.onConnected?.(true);
    };

    h.onConnected?.(false);

    for (const name of SSE_EVENT_TYPES) {
      es.addEventListener(name, (raw) => {
        const me = raw as MessageEvent<string>;
        let data: Record<string, unknown> = {};
        try {
          data = me.data ? (JSON.parse(me.data) as Record<string, unknown>) : {};
        } catch {
          console.debug('[sse] 无法解析 payload', name, me.data);
          return;
        }
        if (name === 'heartbeat') return;
        h.onEvent({
          id: me.lastEventId || String(data.tick ?? ''),
          type: name,
          data,
          receivedAt: Date.now(),
        });
      });
    }

    // 未知 event: 名（后端新增）——忽略但留痕
    es.onmessage = (raw) => {
      const me = raw as MessageEvent<string>;
      console.debug('[sse] 未注册的事件类型，已忽略', me.type, me.data);
    };

    es.onerror = () => {
      h.onConnected?.(false);
      this.close();
      if (!this.started) return;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    this.clearTimer();
    const delay = this.backoff;
    this.backoff = Math.min(BACKOFF_MAX, this.backoff * 2);
    this.timer = window.setTimeout(() => {
      this.timer = null;
      const h = this.handlers;
      const lastTick = h?.getLastTick?.() ?? 0;
      if (h?.replay && lastTick > 0) {
        void h.replay(lastTick).finally(() => this.open());
      } else {
        this.open();
      }
    }, delay);
  }

  private close(): void {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }

  private clearTimer(): void {
    if (this.timer !== null) {
      window.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private installVisibility(): void {
    const onHide = () => {
      this.hiddenSince = Date.now();
    };
    const onShow = () => {
      const since = this.hiddenSince;
      this.hiddenSince = null;
      if (!this.started) return;
      // 长时间隐藏期间由浏览器断流，这里按需重连
      if (since !== null && Date.now() - since > HIDDEN_CLOSE_MS) {
        this.backoff = BACKOFF_START;
        if (!this.es) this.scheduleReconnect();
      } else if (!this.es) {
        this.open();
      }
    };
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') onHide();
      else onShow();
    });
  }
}

export const sse = new SseClient();

// ── 提示文案 ──

export const OAUTH_ERROR_TEXT: Record<string, string> = {
  missing_code: '知乎没有返回授权码',
  state_mismatch: '登录状态已过期，请重试',
  token_exchange_failed: '换取登录凭证失败',
  zhihu_unavailable: '知乎接口暂时不可用',
};

export function oauthErrorText(reason: string | null): string | null {
  if (!reason) return null;
  return OAUTH_ERROR_TEXT[reason] ?? '登录失败，请重试';
}
