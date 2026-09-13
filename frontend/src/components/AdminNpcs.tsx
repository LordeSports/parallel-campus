/** NPC 状态与人格编辑。 */
import { useState } from 'react';
import { adminApi } from '../api/endpoints';
import type { LocationView, NpcRequest, NpcView, PersonaFile } from '../api/types';
import { Field, Section, LocationOptions, fieldClass, type AdminAction } from './AdminForms';

function emptyNpc(): NpcRequest {
  return { name: '新同学', avatar_key: 'av_01', location_id: 'dorm', activity: '认识校园', energy: 100,
    mood_valence: 0, mood_arousal: 0, is_asleep: false, is_active: true,
    persona: { display_name: '新同学', archetype: '喜欢认识新朋友', mbti_like: { E_I: 0, S_N: 0, T_F: 0, J_P: 0 }, big_five: { O: .5, C: .5, E: .5, A: .5, N: .5 },
      interests: [{ topic: '校园生活', weight: .8, evidence: [] }, { topic: '知识分享', weight: .6, evidence: [] }, { topic: '旅行', weight: .5, evidence: [] }],
      summary: '喜欢探索校园，在日常相处中慢慢认识朋友。', values: ['真诚'], appearance: '穿着简单，背着帆布包', campus_identity: { major: '未定', grade: '大二', club: null } } };
}

function fromNpc(npc: NpcView): NpcRequest {
  return { name: npc.name, avatar_key: npc.avatar_key, persona: npc.persona, location_id: npc.location_id,
    activity: npc.activity ?? '', energy: npc.energy ?? 100, mood_valence: npc.mood?.valence ?? 0,
    mood_arousal: npc.mood?.arousal ?? 0, is_asleep: npc.is_asleep ?? false, is_active: npc.is_active };
}

export default function AdminNpcs({ npcs, locations, busy, run }: { npcs: NpcView[]; locations: LocationView[]; busy: boolean; run: AdminAction }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState<NpcRequest>(emptyNpc);
  const [personaJson, setPersonaJson] = useState(JSON.stringify(form.persona, null, 2));
  const [advanced, setAdvanced] = useState(false);
  function select(npc?: NpcView) {
    const value = npc ? fromNpc(npc) : emptyNpc(); setSelected(npc?.id ?? null); setForm(value);
    setPersonaJson(JSON.stringify(value.persona, null, 2)); setAdvanced(false);
  }
  return <div className="grid items-start gap-6 lg:grid-cols-[280px_1fr]">
    <Section title={`校园 NPC · ${npcs.length}`}><button className="btn-primary w-full" onClick={() => select()}>＋ 新增 NPC</button>
      <ul className="max-h-[60vh] space-y-2 overflow-auto">{npcs.map(npc => <li key={npc.id}><button className={`w-full rounded-xl border p-3 text-left transition-colors ${selected === npc.id ? 'border-brand-500 bg-brand-50' : 'border-transparent hover:bg-black/5'}`} onClick={() => select(npc)}>
        <span className="block font-medium">{npc.name}<span className="float-right text-xs text-muted">{npc.is_active ? '启用' : '停用'}</span></span>
        <span className="mt-1 block text-xs text-muted">{locations.find(l => l.id === npc.location_id)?.name} · {npc.is_asleep ? '休息中' : npc.activity}</span>
      </button></li>)}</ul></Section>
    <Section title={selected ? '编辑 NPC' : '创建 NPC'} description="修改后立即生效；运行中的 NPC 会继续自主行动。停用保留记忆与关系。">
      <form className="space-y-5" onSubmit={e => { e.preventDefault(); void run(async () => {
        const persona = advanced ? JSON.parse(personaJson) as PersonaFile : form.persona;
        const payload = { ...form, persona: { ...persona, display_name: form.name } };
        const saved = selected ? await adminApi.updateNpc(selected, payload) : await adminApi.createNpc(payload);
        select(saved);
      }, 'NPC 已保存'); }}>
        <div className="grid gap-4 sm:grid-cols-2"><Field label="名字"><input className={fieldClass} required maxLength={24} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="地点"><select className={fieldClass} value={form.location_id} onChange={e => setForm({ ...form, location_id: e.target.value as NpcRequest['location_id'] })}><LocationOptions locations={locations} /></select></Field></div>
        <div className="grid gap-4 sm:grid-cols-2"><Field label="当前活动"><input className={fieldClass} maxLength={30} value={form.activity} onChange={e => setForm({ ...form, activity: e.target.value })} /></Field>
          <Field label="精力（0–100）"><input className={fieldClass} required type="number" min="0" max="100" value={form.energy} onChange={e => setForm({ ...form, energy: Number(e.target.value) })} /></Field></div>
        <div className="grid gap-4 sm:grid-cols-2"><Field label="心情愉悦度（-1–1）"><input className={fieldClass} required type="number" min="-1" max="1" step="0.1" value={form.mood_valence} onChange={e => setForm({ ...form, mood_valence: Number(e.target.value) })} /></Field>
          <Field label="心情唤醒度（-1–1）"><input className={fieldClass} required type="number" min="-1" max="1" step="0.1" value={form.mood_arousal} onChange={e => setForm({ ...form, mood_arousal: Number(e.target.value) })} /></Field></div>
        <div className="flex flex-wrap gap-6 text-sm"><label className="flex gap-2"><input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} />参与模拟</label>
          <label className="flex gap-2"><input type="checkbox" checked={form.is_asleep} onChange={e => setForm({ ...form, is_asleep: e.target.checked })} />正在休息</label></div>
        <Field label="一句话人设"><input className={fieldClass} required maxLength={20} disabled={advanced} value={form.persona.archetype} onChange={e => setForm({ ...form, persona: { ...form.persona, archetype: e.target.value } })} /></Field>
        <Field label="人格描述"><textarea className={fieldClass} rows={3} required maxLength={400} disabled={advanced} value={form.persona.summary} onChange={e => setForm({ ...form, persona: { ...form.persona, summary: e.target.value } })} /></Field>
        <Field label="外观"><input className={fieldClass} maxLength={80} disabled={advanced} value={form.persona.appearance ?? ''} onChange={e => setForm({ ...form, persona: { ...form.persona, appearance: e.target.value } })} /></Field>
        <label className="flex gap-2 text-sm"><input type="checkbox" checked={advanced} onChange={e => { setAdvanced(e.target.checked); if (e.target.checked) setPersonaJson(JSON.stringify(form.persona, null, 2)); }} />高级人格编辑（兴趣、性格、说话风格）</label>
        {advanced && <Field label="完整人格 JSON" hint="按现有结构填写，保存时由后端校验。"><textarea className={`${fieldClass} font-mono text-xs`} rows={16} value={personaJson} onChange={e => setPersonaJson(e.target.value)} /></Field>}
        <button className="btn-primary" disabled={busy}>{selected ? '保存 NPC' : '创建 NPC'}</button>
      </form>
    </Section>
  </div>;
}
