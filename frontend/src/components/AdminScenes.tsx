/** 即时场景布置与结束。 */
import { useState } from 'react';
import { adminApi } from '../api/endpoints';
import type { ActiveEventView, LocationView, SceneRequest } from '../api/types';
import { Field, Section, LocationOptions, fieldClass, type AdminAction } from './AdminForms';

export default function AdminScenes({ scenes, locations, busy, run }: { scenes: ActiveEventView[]; locations: LocationView[]; busy: boolean; run: AdminAction }) {
  const [form, setForm] = useState<SceneRequest>({ title: '', description: '', location_id: 'field', duration_ticks: 6 });
  const [tags, setTags] = useState('');
  return <div className="grid items-start gap-6 lg:grid-cols-2"><Section title="布置校园场景" description="场景立即出现在指定地点，角色会根据兴趣决定是否参与。">
    <form className="space-y-4" onSubmit={e => { e.preventDefault(); void run(() => adminApi.createScene({ ...form, tags: tags.split(/[,，]/).map(t => t.trim()).filter(Boolean) }), '场景已发布').then(ok => { if (ok) { setForm({ ...form, title: '', description: '' }); setTags(''); } }); }}>
      <Field label="场景标题"><input className={fieldClass} required maxLength={30} placeholder="湖畔读书会" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} /></Field>
      <Field label="场景描述"><textarea className={fieldClass} rows={3} maxLength={120} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></Field>
      <div className="grid grid-cols-2 gap-4"><Field label="地点"><select className={fieldClass} value={form.location_id} onChange={e => setForm({ ...form, location_id: e.target.value as SceneRequest['location_id'] })}><LocationOptions locations={locations} /></select></Field>
        <Field label="持续步数"><input className={fieldClass} required type="number" min="1" max="96" value={form.duration_ticks} onChange={e => setForm({ ...form, duration_ticks: Number(e.target.value) })} /></Field></div>
      <Field label="兴趣标签" hint="逗号分隔，最多 5 个，每个最多 12 字。"><input className={fieldClass} value={tags} onChange={e => setTags(e.target.value)} placeholder="阅读, 文学" /></Field>
      <button className="btn-primary" disabled={busy}>发布场景</button>
    </form></Section><Section title="场景列表">{scenes.length === 0 && <p className="text-sm text-muted">还没有场景</p>}
    <ul className="space-y-3">{scenes.map(scene => <li key={scene.id} className="rounded-2xl bg-black/[.025] p-4">
      <div className="flex justify-between gap-3"><h3 className="font-medium">{scene.title}</h3><span className="chip">{scene.status === 'active' ? '进行中' : scene.status === 'ended' ? '已结束' : '待开始'}</span></div>
      <p className="my-2 text-sm text-muted">{scene.description}</p><div className="flex items-center justify-between gap-2 text-xs text-muted"><span>{locations.find(l => l.id === scene.location_id)?.name} · #{scene.start_tick}–{scene.end_tick}</span>
        {scene.status !== 'ended' && <button className="btn-outline text-xs" disabled={busy} onClick={() => void run(() => adminApi.endScene(scene.id), '场景已结束')}>结束场景</button>}</div>
    </li>)}</ul></Section></div>;
}
