/** 人格三步（spec/07 §3.2）。 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { avatarApi, personaApi } from '../api/endpoints';
import type { CharacterDetailView, PersonaFile } from '../api/types';
import DeployForm from '../components/DeployForm';
import PersonaEditor from '../components/PersonaEditor';
import Toast from '../components/Toast';
import { useSession } from '../store/session';

const STAGES = [
  '正在读你的回答…',
  '正在看你关注了谁…',
  '正在拆解你喜欢的话题…',
  '正在写画像…',
];

type Step = 'loading' | 'edit' | 'deploy' | 'timeout';

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
        .catch(() => void generate());
      void avatarApi
        .me()
        .then((me) => {
          setExisting(me);
          setStep('deploy');
        })
        .catch(() => setStep('deploy'));
      return;
    }
    void generate();
  }, [user, generate]);

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
          const idx = step === 'edit' ? 1 : 2;
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
