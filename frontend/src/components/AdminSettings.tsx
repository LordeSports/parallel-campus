/** API 配置仅提交新 Key，绝不回显已有 Key。 */
import { useState } from 'react';
import { adminApi } from '../api/endpoints';
import type { ApiSettingsRequest, ApiSettingsView } from '../api/types';
import { Field, Section, fieldClass, type AdminAction } from './AdminForms';

export default function AdminSettings({ settings, busy, run }: { settings: ApiSettingsView; busy: boolean; run: AdminAction }) {
  const [form, setForm] = useState<ApiSettingsRequest>({ llm_base_url: settings.llm_base_url,
    llm_model_strong: settings.llm_model_strong, llm_model_cheap: settings.llm_model_cheap,
    zhihu_oauth_app_id: settings.zhihu_oauth_app_id, llm_api_key: '', zhihu_access_secret: '', zhihu_oauth_app_key: '' });
  const update = (key: keyof ApiSettingsRequest, value: string | boolean) => setForm(previous => ({ ...previous, [key]: value }));
  const secrets = [
    { key: 'llm_api_key', clear: 'clear_llm_api_key', label: 'LLM API Key', configured: settings.llm_api_key_configured },
    { key: 'zhihu_access_secret', clear: 'clear_zhihu_access_secret', label: '知乎 Access Secret', configured: settings.zhihu_access_secret_configured },
    { key: 'zhihu_oauth_app_key', clear: 'clear_zhihu_oauth_app_key', label: '知乎 OAuth App Key', configured: settings.zhihu_oauth_app_key_configured },
  ] as const;
  return <Section title="API 配置" description="保存后生效，加密保存在数据卷中。留空保留已有密钥，勾选清除才会移除。">
    {settings.dev_mode && <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">当前为开发模式，知乎接口使用示例数据；真实接入需要在部署环境设置 DEV_MODE=false。</p>}
    <form className="space-y-5" onSubmit={e => { e.preventDefault(); void run(() => adminApi.saveSettings(form), 'API 配置已加密保存').then(ok => {
      if (ok) setForm(previous => ({ ...previous, llm_api_key: '', zhihu_access_secret: '', zhihu_oauth_app_key: '', clear_llm_api_key: false, clear_zhihu_access_secret: false, clear_zhihu_oauth_app_key: false }));
    }); }}>
      <Field label="LLM Base URL" hint="更换地址时须重新输入 Key，避免把已有 Key 发送到其他服务。"><input className={fieldClass} type="url" required maxLength={300} value={form.llm_base_url} onChange={e => update('llm_base_url', e.target.value)} /></Field>
      <div className="grid gap-4 sm:grid-cols-2"><Field label="高质量模型"><input className={fieldClass} required maxLength={80} value={form.llm_model_strong} onChange={e => update('llm_model_strong', e.target.value)} /></Field>
        <Field label="经济模型"><input className={fieldClass} required maxLength={80} value={form.llm_model_cheap} onChange={e => update('llm_model_cheap', e.target.value)} /></Field></div>
      <Field label="知乎 OAuth App ID"><input className={fieldClass} maxLength={200} value={form.zhihu_oauth_app_id} onChange={e => update('zhihu_oauth_app_id', e.target.value)} /></Field>
      <div className="grid gap-5 lg:grid-cols-3">{secrets.map(item => <div key={item.key} className="rounded-2xl bg-black/[.025] p-4">
        <Field label={`${item.label} · ${item.configured ? '已配置' : '未配置'}`}><input className={fieldClass} type="password" autoComplete="new-password" maxLength={4096} value={form[item.key] ?? ''} onChange={e => update(item.key, e.target.value)} placeholder="输入新密钥" disabled={Boolean(form[item.clear])} /></Field>
        <label className="mt-3 flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={Boolean(form[item.clear])} onChange={e => update(item.clear, e.target.checked)} />清除已有密钥</label>
      </div>)}</div><button className="btn-primary" disabled={busy}>保存 API 配置</button>
    </form>
  </Section>;
}
