/** 对话式画像访谈：LLM 一次一问，画像随回答逐步长出来。 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { personaApi } from '../api/endpoints';
import type { InterviewView, PersonaFile } from '../api/types';

interface Msg {
  role: 'assistant' | 'user';
  text: string;
  question?: string;
}

const SUGGESTIONS = [
  '随便聊聊就行',
  '我是理工科的，喜欢折腾数码',
  '话不多，但熟人面前话很多',
  '先按你的判断来',
];

export default function PersonaInterview({ onDone }: { onDone: (file: PersonaFile) => void }) {
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [question, setQuestion] = useState('');
  const [progress, setProgress] = useState(30);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const listRef = useRef<HTMLDivElement | null>(null);

  const apply = useCallback((v: InterviewView) => {
    setSessionId(v.session_id);
    const raw = (v.messages ?? []) as unknown as Msg[];
    setMessages(raw.filter((m) => m && typeof m.text === 'string'));
    setQuestion(v.question ?? '');
    setProgress(v.progress ?? 0);
    setDone(Boolean(v.done));
  }, []);

  useEffect(() => {
    setBusy(true);
    personaApi
      .interviewStart()
      .then(apply)
      .catch((e) => setError(e instanceof Error ? e.message : '访谈启动失败'))
      .finally(() => setBusy(false));
  }, [apply]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, question]);

  const send = async (text: string) => {
    const clean = text.trim();
    if (!clean || busy || !sessionId) return;
    setInput('');
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: 'user', text: clean }]);
    try {
      const v = await personaApi.interviewAnswer(sessionId, clean);
      apply(v);
    } catch (e) {
      setError(e instanceof Error ? e.message : '发送失败，请重试');
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await personaApi.interviewFinish(sessionId);
      onDone(res.file);
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成画像失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card flex h-[62vh] min-h-[460px] flex-col overflow-hidden">
      {/* 进度 */}
      <div className="border-b border-black/5 px-4 py-2.5">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-ink">对话生成画像</span>
          <span className="tabular-nums text-muted">{progress}%</span>
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-black/5">
          <div
            className="h-full rounded-full bg-brand-500 transition-all duration-500"
            style={{ width: `${Math.min(100, progress)}%` }}
          />
        </div>
      </div>

      {/* 消息 */}
      <div ref={listRef} className="scroll-thin flex-1 space-y-3 overflow-auto px-4 py-3">
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={[
                'max-w-[80%] rounded-2xl px-3 py-2 text-sm leading-relaxed',
                m.role === 'user'
                  ? 'rounded-br-md bg-brand-500 text-white'
                  : 'rounded-bl-md bg-black/[.04] text-ink',
              ].join(' ')}
            >
              {m.text}
              {m.question ? <p className="mt-2 font-medium">{m.question}</p> : null}
            </div>
          </div>
        ))}
        {busy && messages.length > 0 && (
          <div className="flex justify-start">
            <div className="rounded-2xl rounded-bl-md bg-black/[.04] px-3 py-2 text-sm text-muted">
              正在思考…
            </div>
          </div>
        )}
      </div>

      {error && <p className="mx-4 mb-2 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{error}</p>}

      {/* 输入区 */}
      <div className="border-t border-black/5 px-4 py-3">
        {done ? (
          <div className="space-y-2.5">
            <p className="text-xs text-muted">信息够了，画像已经生成。可以去看一眼，继续调整细节。</p>
            <button type="button" className="btn-primary w-full py-2.5" disabled={busy} onClick={() => void finish()}>
              {busy ? '生成中…' : '查看生成的画像'}
            </button>
          </div>
        ) : (
          <>
            <div className="scroll-thin mb-2 flex gap-1.5 overflow-x-auto pb-1">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="shrink-0 rounded-full bg-black/[.04] px-2.5 py-1 text-[11px] text-muted hover:bg-black/[.07]"
                  disabled={busy}
                  onClick={() => void send(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void send(input);
              }}
            >
              <input
                className="flex-1 rounded-xl border border-black/10 px-3 py-2 text-sm outline-none focus:border-brand-500"
                placeholder="用一句话回答就行…"
                maxLength={400}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={busy}
              />
              <button type="submit" className="btn-primary px-4" disabled={busy || !input.trim()}>
                发送
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
