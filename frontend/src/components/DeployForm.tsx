/** 投放表单（spec/07 §3.2 Step 3）。 */

import { useState } from 'react';

import { personaApi } from '../api/endpoints';
import type { CharacterDetailView, DeployRequest, PersonaFile } from '../api/types';
import { AVATAR_KEYS, avatarMeta } from '../avatar';

const GRADES: DeployRequest['grade'][] = ['大一', '大二', '大三', '大四', '研一', '研二', '研三'];

export default function DeployForm({
  file,
  existing,
  onDeployed,
}: {
  file: PersonaFile;
  existing: CharacterDetailView | null;
  onDeployed: (c: CharacterDetailView) => void;
}) {
  const [displayName, setDisplayName] = useState(existing?.name ?? file.display_name);
  const [avatarKey, setAvatarKey] = useState(
    AVATAR_KEYS.includes(existing?.avatar_key ?? '') ? (existing?.avatar_key as string) : AVATAR_KEYS[0],
  );
  const [appearance, setAppearance] = useState<string>(
    existing?.appearance ?? file.appearance ?? '',
  );
  const [major, setMajor] = useState(
    existing?.identity?.major ?? file.campus_identity?.major ?? '',
  );
  const [grade, setGrade] = useState<string>(
    String(existing?.identity?.grade ?? file.campus_identity?.grade ?? '大一'),
  );
  const [club, setClub] = useState<string>(
    String(existing?.identity?.club ?? file.campus_identity?.club ?? ''),
  );
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const redeploy = Boolean(existing);

  return (
    <div className="space-y-5">
      {redeploy && (
        <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
          分身已经在校园里了。重新投放会保留记忆与关系。
        </div>
      )}

      <section className="card space-y-4 p-4">
        <div>
          <label className="mb-1 block text-xs text-muted">校园里的名字</label>
          <input
            className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm outline-none focus:border-brand-500"
            value={displayName}
            maxLength={16}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs text-muted">挑一个头像</label>
          <div className="grid grid-cols-8 gap-1.5">
            {AVATAR_KEYS.map((k) => {
              const meta = avatarMeta(k);
              return (
                <button
                  key={k}
                  type="button"
                  title={k}
                  style={{ background: meta.bg }}
                  className={[
                    'grid aspect-square place-items-center rounded-lg text-lg transition-all',
                    avatarKey === k ? 'ring-2 ring-brand-500' : 'hover:brightness-95',
                  ].join(' ')}
                  onClick={() => setAvatarKey(k)}
                >
                  <span className="emoji">{meta.emoji}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs text-muted">外形描述</label>
          <textarea
            className="w-full resize-none rounded-xl border border-black/10 p-3 text-xs leading-relaxed outline-none focus:border-brand-500"
            rows={2}
            value={appearance}
            onChange={(e) => setAppearance(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs text-muted">专业</label>
            <input
              className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm outline-none focus:border-brand-500"
              value={major}
              placeholder="计算机科学"
              onChange={(e) => setMajor(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted">年级</label>
            <select
              className="w-full rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500"
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
            >
              {GRADES.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs text-muted">社团（可选）</label>
          <input
            className="w-full rounded-xl border border-black/10 px-3 py-2 text-sm outline-none focus:border-brand-500"
            value={club}
            placeholder="摄影社"
            onChange={(e) => setClub(e.target.value)}
          />
        </div>
      </section>

      {err && <div className="rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">{err}</div>}

      <button
        type="button"
        className="btn-primary w-full py-3"
        disabled={busy || done || !displayName.trim()}
        onClick={() => {
          setBusy(true);
          setErr(null);
          personaApi
            .deploy(
              {
                display_name: displayName.trim(),
                avatar_key: avatarKey,
                appearance,
                major,
                grade: grade as NonNullable<DeployRequest['grade']>,
                club: club.trim() || null,
              },
              redeploy,
            )
            .then((c) => {
              setDone(true);
              window.setTimeout(() => onDeployed(c), 1500);
            })
            .catch((e) => setErr(e instanceof Error ? e.message : '投放失败'))
            .finally(() => setBusy(false));
        }}
      >
        {done ? '投放成功！' : busy ? '正在进入校园…' : redeploy ? '重新投放' : '投放到校园'}
      </button>
    </div>
  );
}
