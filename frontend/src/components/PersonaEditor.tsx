/** 人格编辑（spec/07 §3.2 Step 2）。 */

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts';

import type { Interest, PersonaFile, Stance } from '../api/types';

const BIG_FIVE_LABELS: Record<string, string> = {
  openness: '开放性',
  conscientiousness: '尽责性',
  extraversion: '外向性',
  agreeableness: '宜人性',
  neuroticism: '情绪性',
};

const MBTI_PAIRS: { key: string; left: string; right: string }[] = [
  { key: 'EI', left: 'E 外向', right: 'I 内向' },
  { key: 'SN', left: 'S 实感', right: 'N 直觉' },
  { key: 'TF', left: 'T 思考', right: 'F 情感' },
  { key: 'JP', left: 'J 判断', right: 'P 知觉' },
];

function Slider({
  label,
  left,
  right,
  value,
  onChange,
}: {
  label?: string;
  left: string;
  right: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      {label && <p className="mb-1 text-xs text-muted">{label}</p>}
      <div className="flex items-center gap-2">
        <span className="w-14 shrink-0 text-right text-[11px] text-muted">{left}</span>
        <input
          type="range"
          min={-1}
          max={1}
          step={0.1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-1.5 flex-1 accent-brand-500"
        />
        <span className="w-14 shrink-0 text-[11px] text-muted">{right}</span>
      </div>
    </div>
  );
}

export default function PersonaEditor({
  file,
  onChange,
  onSave,
  onRegenerate,
  saving,
  regenLeft,
}: {
  file: PersonaFile;
  onChange: (f: PersonaFile) => void;
  onSave: () => void;
  onRegenerate: () => void;
  saving: boolean;
  regenLeft: number;
}) {
  const patch = (p: Partial<PersonaFile>) => onChange({ ...file, ...p });

  const mbti = file.mbti_like ?? {};
  const bigFive = file.big_five ?? {};
  const interests = file.interests ?? [];
  const stances = file.stances ?? [];

  const setInterestWeight = (i: number, w: number) => {
    const next = interests.map((it, j) => (j === i ? { ...it, weight: w } : it));
    patch({ interests: next });
  };
  const removeInterest = (i: number) => patch({ interests: interests.filter((_, j) => j !== i) });
  const addInterest = (topic: string) => {
    if (!topic.trim()) return;
    patch({ interests: [...interests, { topic: topic.trim(), weight: 0.5, evidence: [] } as Interest] });
  };

  const radarData = Object.entries(BIG_FIVE_LABELS).map(([k, label]) => ({
    label,
    value: Math.round((bigFive[k] ?? 0.5) * 100),
  }));

  const summaryLen = file.summary?.length ?? 0;

  return (
    <div className="space-y-5">
      {/* 原型 + 简介 */}
      <section className="card space-y-3 p-4">
        <div>
          <label className="mb-1 block text-xs text-muted">人格原型</label>
          <input
            className="w-full rounded-xl border border-black/10 px-3 py-2 text-lg font-medium outline-none focus:border-brand-500"
            value={file.archetype}
            onChange={(e) => patch({ archetype: e.target.value })}
          />
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <label className="text-xs text-muted">画像摘要</label>
            <span
              className={[
                'text-[11px]',
                summaryLen < 150 || summaryLen > 350 ? 'text-amber-600' : 'text-muted',
              ].join(' ')}
            >
              {summaryLen}/150–350
            </span>
          </div>
          <textarea
            className="w-full resize-none rounded-xl border border-black/10 p-3 text-sm leading-relaxed outline-none focus:border-brand-500"
            rows={5}
            value={file.summary}
            onChange={(e) => patch({ summary: e.target.value })}
          />
        </div>
      </section>

      {/* MBTI 四条滑条 */}
      <section className="card space-y-3 p-4">
        <h3 className="text-sm font-medium text-ink">性格维度</h3>
        {MBTI_PAIRS.map((p) => (
          <Slider
            key={p.key}
            left={p.left}
            right={p.right}
            value={mbti[p.key] ?? 0}
            onChange={(v) => patch({ mbti_like: { ...mbti, [p.key]: v } })}
          />
        ))}
      </section>

      {/* 大五雷达 + 滑条 */}
      <section className="card p-4">
        <h3 className="mb-2 text-sm font-medium text-ink">五大人格</h3>
        <div className="h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={radarData} outerRadius="70%">
              <PolarGrid stroke="#00000015" />
              <PolarAngleAxis dataKey="label" tick={{ fontSize: 11, fill: '#6b7280' }} />
              <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
              <Radar
                dataKey="value"
                stroke="#0084ff"
                fill="#0084ff"
                fillOpacity={0.25}
                strokeWidth={2}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-2 space-y-2.5">
          {Object.entries(BIG_FIVE_LABELS).map(([k, label]) => (
            <Slider
              key={k}
              label={label}
              left="低"
              right="高"
              value={bigFive[k] ?? 0.5}
              onChange={(v) => patch({ big_five: { ...bigFive, [k]: v } })}
            />
          ))}
        </div>
      </section>

      {/* 兴趣标签云 */}
      <section className="card p-4">
        <h3 className="mb-2.5 text-sm font-medium text-ink">兴趣标签</h3>
        <div className="flex flex-wrap items-start gap-2">
          {interests.map((it, i) => (
            <span
              key={`${it.topic}-${i}`}
              className="group relative inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-brand-700"
              style={{ fontSize: `${11 + Math.round((it.weight ?? 0.5) * 5)}px` }}
            >
              {it.topic}
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={it.weight ?? 0.5}
                onChange={(e) => setInterestWeight(i, Number(e.target.value))}
                className="h-1 w-12 accent-brand-500"
                title={`权重 ${it.weight}`}
              />
              <button
                type="button"
                className="text-brand-400 hover:text-red-500"
                onClick={() => removeInterest(i)}
              >
                ✕
              </button>
              {(it.evidence ?? []).length > 0 && (
                <span className="pointer-events-none absolute -top-7 left-0 z-10 hidden whitespace-nowrap rounded-md bg-ink px-2 py-1 text-[10px] text-white group-hover:block">
                  依据：{it.evidence?.[0]}
                </span>
              )}
            </span>
          ))}
        </div>
        <form
          className="mt-3"
          onSubmit={(e) => {
            e.preventDefault();
            const input = (e.currentTarget.elements.namedItem('topic') as HTMLInputElement) ?? null;
            if (input) {
              addInterest(input.value);
              input.value = '';
            }
          }}
        >
          <input
            name="topic"
            className="w-full rounded-xl border border-dashed border-black/15 px-3 py-1.5 text-xs outline-none focus:border-brand-500"
            placeholder="+ 添加一个兴趣（回车确认）"
          />
        </form>
      </section>

      {/* 立场 */}
      <section className="card p-4">
        <h3 className="mb-2.5 text-sm font-medium text-ink">观点与立场</h3>
        <div className="space-y-2">
          {stances.map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <textarea
                className="min-w-0 flex-1 resize-none rounded-xl border border-black/10 p-2 text-xs outline-none focus:border-brand-500"
                rows={2}
                value={s.text}
                onChange={(e) => {
                  const next = stances.map((x, j) =>
                    j === i ? ({ ...x, text: e.target.value } as Stance) : x,
                  );
                  patch({ stances: next });
                }}
              />
              <button
                type="button"
                className="btn-ghost px-2 py-1 text-xs"
                onClick={() => patch({ stances: stances.filter((_, j) => j !== i) })}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          className="btn-outline mt-2 px-3 py-1.5 text-xs"
          onClick={() => patch({ stances: [...stances, { text: '', evidence: [] }] })}
        >
          + 添加立场
        </button>
      </section>

      {/* 价值观 / 说话风格 / 社交 */}
      <section className="grid gap-4 md:grid-cols-2">
        <div className="card p-4">
          <h3 className="mb-2 text-sm font-medium text-ink">价值观（≤4 个）</h3>
          <div className="flex flex-wrap gap-1.5">
            {(file.values ?? []).map((v, i) => (
              <span key={`${v}-${i}`} className="chip bg-amber-50 text-amber-700">
                {v}
                <button
                  type="button"
                  className="ml-0.5 opacity-60 hover:opacity-100"
                  onClick={() =>
                    patch({ values: (file.values ?? []).filter((_, j) => j !== i) })
                  }
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
          {(file.values ?? []).length < 4 && (
            <form
              className="mt-2"
              onSubmit={(e) => {
                e.preventDefault();
                const input = e.currentTarget.elements.namedItem('val') as HTMLInputElement;
                if (input.value.trim()) {
                  patch({ values: [...(file.values ?? []), input.value.trim()] });
                  input.value = '';
                }
              }}
            >
              <input
                name="val"
                className="w-full rounded-xl border border-dashed border-black/15 px-3 py-1.5 text-xs outline-none focus:border-brand-500"
                placeholder="+ 添加价值观"
              />
            </form>
          )}
        </div>

        <div className="card space-y-3 p-4">
          <h3 className="text-sm font-medium text-ink">表达方式</h3>
          <div>
            <label className="mb-1 block text-[11px] text-muted">语气</label>
            <input
              className="w-full rounded-lg border border-black/10 px-2.5 py-1.5 text-xs outline-none focus:border-brand-500"
              value={file.speaking_style?.tone ?? ''}
              onChange={(e) =>
                patch({ speaking_style: { ...file.speaking_style, tone: e.target.value } })
              }
            />
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-muted">爱用 emoji</span>
            <button
              type="button"
              className={[
                'relative h-5 w-9 rounded-full transition-colors',
                file.speaking_style?.emoji ? 'bg-brand-500' : 'bg-black/15',
              ].join(' ')}
              onClick={() =>
                patch({
                  speaking_style: { ...file.speaking_style, emoji: !file.speaking_style?.emoji },
                })
              }
            >
              <span
                className={[
                  'absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all',
                  file.speaking_style?.emoji ? 'left-[1.15rem]' : 'left-0.5',
                ].join(' ')}
              />
            </button>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-muted">发言长度</label>
            <div className="flex gap-1.5">
              {(['短', '中', '长'] as const).map((l) => (
                <button
                  key={l}
                  type="button"
                  className={[
                    'flex-1 rounded-lg py-1 text-xs transition-colors',
                    file.speaking_style?.length === l
                      ? 'bg-brand-500 text-white'
                      : 'bg-black/5 text-muted',
                  ].join(' ')}
                  onClick={() => patch({ speaking_style: { ...file.speaking_style, length: l } })}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-muted">社交倾向</label>
            <div className="flex gap-1.5">
              {(['独处', '小圈子', '广交'] as const).map((g) => (
                <button
                  key={g}
                  type="button"
                  className={[
                    'flex-1 rounded-lg py-1 text-xs transition-colors',
                    file.social?.group_pref === g
                      ? 'bg-brand-500 text-white'
                      : 'bg-black/5 text-muted',
                  ].join(' ')}
                  onClick={() => patch({ social: { ...file.social, group_pref: g } })}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 底部动作 */}
      <div className="sticky bottom-0 -mx-3 flex items-center justify-between gap-3 border-t border-black/5 bg-paper/95 px-3 py-3 backdrop-blur">
        <button
          type="button"
          className="btn-ghost text-xs"
          onClick={onRegenerate}
          disabled={regenLeft <= 0}
        >
          重新生成（剩 {regenLeft} 次）
        </button>
        <button type="button" className="btn-primary px-6" onClick={onSave} disabled={saving}>
          {saving ? '保存中…' : '保存'}
        </button>
      </div>
    </div>
  );
}
