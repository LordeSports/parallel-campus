/** 人格三步（spec/07 §3.2）。 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { avatarApi, personaApi } from '../api/endpoints';
import type { CharacterDetailView, PersonaFile } from '../api/types';
import DeployForm from '../components/DeployForm';
import PersonaEditor from '../components/PersonaEditor';
import PersonaInterview from '../components/PersonaInterview';
import Toast from '../components/Toast';
import { useSession } from '../store/session';

const STAGES = [
  '正在读你的回答…',
  '正在看你关注了谁…',
  '正在拆解你喜欢的话题…',
  '正在写画像…',
];

type Step = 'choose' | 'interview' | 'loading' | 'edit' | 'deploy' | 'timeout';

/** 手动编辑的起点：中性画像（与后端 _neutral_persona 一致，PUT /persona 会落库）。 */
function neutralFile(name: string): PersonaFile {
  return {
    display_name: name || '未命名',
    archetype: '还在认识自己的同学',
    mbti_like: { E_I: 0, S_N: 0, T_F: 0, J_P: 0 },
    big_five: { O: 0.5, C: 0.5, E: 0.5, A: 0.5, N: 0.5 },
    interests: [
      { topic: '校园生活', weight: 0.6, evidence: [] },
      { topic: '知识分享', weight: 0.5, evidence: [] },
      { topic: '旅行', weight: 0.4, evidence: [] },
    ],
    stances: [],
    speaking_style: { tone: '自然', emoji: false, length: '中', catchphrases: [] },
    values: ['真诚'],
    social: { initiative: 0.5, group_pref: '小圈子', avoid_topics: ['个人隐私'] },
    campus_identity: { major: '未定', grade: '大二', club: null },
    appearance: '穿得简单，走路不急',
    summary:
      '这位同学的画像还在草稿阶段。你可以直接改每一项——改完保存就能投放，之后也随时能回来调整。',
  };
}

export default function Persona() {
  const navigate = useNavigate();
  const user = useSession((s) => s.user);
  const fetchMe = useSession((s) => s.fetchMe);

  const [step, setStep] = useState<Step>('loading');
  const [file, setFile] = useState<PersonaFile | null>(null);
  const [thin, setThin] = useState(false);
  const [regenLeft, setRegenLeft] = useState(1);
  const [stageIdx, setStageIdx] = useState(0);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [existing, setExisting] = useState<CharacterDetailView | null>(null);

  const generate = useCallback(
    async (force = false) => {
      setStep('loading');
      setStageIdx(0);
      try {
        const res = await personaApi.generate(force);
        setFile(res.file);
        setThin(Boolean(res.thin));
        setRegenLeft(res.generated_left_today ?? 0);
        setStep('edit');
      } catch {
        setStep('timeout');
      }
    },
    [],
  );

  useEffect(() => {
    if (!user) return;
    if (user.character_id) {
      // 已投放：拉当前人格与分身，停在投放步（spec/07 §1）
      void personaApi
        .get()
        .then((res) => {
          setFile(res.file);
        })
        .catch(() => setStep('choose'));
      void avatarApi
        .me()
        .then((me) => {
          setExisting(me);
          setStep('deploy');
        })
        .catch(() => setStep('deploy'));
      return;
    }
    setStep('choose');
  }, [user]);

  // 阶段文案轮播
  useEffect(() => {
    if (step !== 'loading') return;
    const t = window.setInterval(() => setStageIdx((i) => (i + 1) % STAGES.length), 2200);
    return () => window.clearInterval(t);
  }, [step]);

  // 90s 超时
  useEffect(() => {
    if (step !== 'loading') return;
    const t = window.setTimeout(() => setStep('timeout'), 90_000);
    return () => window.clearTimeout(t);
  }, [step, generate]);

  const save = async () => {
    if (!file) return;
    setSaving(true);
    try {
      const res = await personaApi.save(file);
      setFile(res.file);
      setStep('deploy');
      setToast('已保存');
    } catch (e) {
      setToast(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (step === 'choose') {
    const options: { title: string; hint: string; action: () => void; primary?: boolean }[] = [
      {
        title: '对话生成（推荐）',
        hint: 'LLM 读你的知乎公开内容后，一次一个问题地了解你；画像随回答逐步成形',
        action: () => setStep('interview'),
        primary: true,
      },
      {
        title: '自己编辑参数',
        hint: '跳过生成，直接填写性格、兴趣、说话风格等每一项',
        action: () => {
          setFile(neutralFile(user?.display_name ?? ''));
          setThin(false);
          setStep('edit');
        },
      },
      {
        title: '一键生成（只用知乎数据）',
        hint: '不回答问题，直接从公开内容提炼；内容少时画像会偏薄',
        action: () => void generate(),
      },
    ];
    return (
      <div className="mx-auto max-w-md px-3 py-10">
        <h1 className="text-center text-xl font-semibold text-ink">先把「你」造出来</h1>
        <p className="mt-1.5 text-center text-sm text-muted">
          分身会带着这份人格在校园里自己行动。选一种生成方式：
        </p>
        <div className="mt-6 space-y-3">
          {options.map((opt) => (
            <button
              key={opt.title}
              type="button"
              onClick={opt.action}
              className={[
                'w-full rounded-2xl border px-4 py-3.5 text-left transition-colors',
                opt.primary
                  ? 'border-brand-500 bg-brand-50 hover:bg-brand-100'
                  : 'border-black/10 bg-white hover:bg-black/[.02]',
              ].join(' ')}
            >
              <span className={['block text-sm font-medium', opt.primary ? 'text-brand-700' : 'text-ink'].join(' ')}>
                {opt.title}
              </span>
              <span className="mt-1 block text-xs leading-relaxed text-muted">{opt.hint}</span>
            </button>
          ))}
        </div>
        <p className="mt-5 text-center text-[11px] leading-relaxed text-muted">
          所有方式都能在下一步继续手动微调；人格文件随时可以删除。
        </p>
      </div>
    );
  }

  if (step === 'interview') {
    return (
      <div className="mx-auto max-w-xl px-3 py-4">
        <PersonaInterview
          onDone={(f) => {
            setFile(f);
            setThin(false);
            setStep('edit');
          }}
        />
        <p className="mt-3 text-center text-[11px] text-muted">
          不想聊了？随时可以
          <button
            type="button"
            className="mx-1 text-brand-600 underline-offset-2 hover:underline"
            onClick={() => {
              setFile(neutralFile(user?.display_name ?? ''));
              setStep('edit');
            }}
          >
            改为手动编辑
          </button>
        </p>
      </div>
    );
  }

  if (step === 'loading') {
    return (
      <div className="mx-auto max-w-md px-3 py-20 text-center">
        <div className="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-black/10 border-t-brand-500" />
        <p className="mt-4 text-sm text-ink">{STAGES[stageIdx]}</p>
        <p className="mt-1.5 text-xs text-muted">最多等 90 秒</p>
      </div>
    );
  }

  if (step === 'timeout') {
    return (
      <div className="mx-auto max-w-md px-3 py-20 text-center">
        <p className="text-3xl">⏳</p>
        <h2 className="mt-3 text-base font-medium text-ink">生成有点慢</h2>
        <p className="mt-1.5 text-sm text-muted">可能是知乎接口在忙，再试一次</p>
        <button type="button" className="btn-primary mt-5" onClick={() => void generate()}>
          重试
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-3 py-4">
      {/* 步骤指示 */}
      <div className="mb-4 flex items-center gap-2 text-xs">
        {(['生成', '编辑', '投放'] as const).map((label, i) => {
          const idx = step === 'edit' ? 1 : step === 'deploy' ? 2 : 0;
          const active = i === idx;
          const done = i < idx;
          return (
            <div key={label} className="flex items-center gap-2">
              <span
                className={[
                  'grid h-6 w-6 place-items-center rounded-full text-[11px]',
                  active
                    ? 'bg-brand-500 text-white'
                    : done
                      ? 'bg-brand-50 text-brand-600'
                      : 'bg-black/5 text-muted',
                ].join(' ')}
              >
                {done ? '✓' : i + 1}
              </span>
              <span className={active ? 'font-medium text-ink' : 'text-muted'}>{label}</span>
              {i < 2 && <span className="text-black/15">—</span>}
            </div>
          );
        })}
      </div>

      {thin && step === 'edit' && (
        <div className="mb-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
          你在知乎的公开内容较少，画像可能偏薄，可以自己补充一些
        </div>
      )}

      {step === 'edit' && file && (
        <PersonaEditor
          file={file}
          onChange={setFile}
          onSave={() => void save()}
          onRegenerate={() => void generate(true)}
          saving={saving}
          regenLeft={regenLeft}
        />
      )}

      {step === 'deploy' && file && (
        <DeployForm
          file={file}
          existing={existing}
          onDeployed={() => {
            void fetchMe().then(() => navigate('/campus'));
          }}
        />
      )}

      {toast && <Toast text={toast} onClose={() => setToast(null)} />}
    </div>
  );
}
