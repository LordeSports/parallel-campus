/** 模拟控制、日历跳转与天气调整。 */
import { useState } from 'react';
import { adminApi } from '../api/endpoints';
import type { AdminOverviewView, AdminWeatherRequest, ApiSettingsView, SimulationRequest } from '../api/types';
import { Field, Section, fieldClass, type AdminAction } from './AdminForms';

export default function AdminSimulation({ overview, settings, busy, run }: {
  overview: AdminOverviewView; settings: ApiSettingsView; busy: boolean; run: AdminAction;
}) {
  const [simulation, setSimulation] = useState<SimulationRequest>({
    mode: overview.control_mode as SimulationRequest['mode'], tick_seconds_online: settings.tick_seconds_online,
    tick_seconds_idle: settings.tick_seconds_idle, ticks: 48,
  });
  const [day, setDay] = useState(overview.world.day);
  const [clock, setClock] = useState(`${String(Math.floor(overview.world.minute_of_day / 60)).padStart(2, '0')}:${String(overview.world.minute_of_day % 60).padStart(2, '0')}`);
  const [weather, setWeather] = useState<AdminWeatherRequest>({ kind: overview.world.weather.kind ?? 'sunny', temp_c: overview.world.weather.temp_c ?? 22, text: overview.world.weather.text ?? '' });
  return <div className="grid items-start gap-6 xl:grid-cols-2">
    <Section title="运行速度" description={`当前：${overview.world.time_label} · ${overview.world.tick_seconds} 秒 / 步。每步推进 30 个虚拟分钟；实际速度也取决于模型响应。`}>
      <form className="space-y-5" onSubmit={e => { e.preventDefault(); void run(() => adminApi.simulation(simulation), '运行模式已保存'); }}>
        <Field label="运行模式"><select className={fieldClass} value={simulation.mode} onChange={e => setSimulation({ ...simulation, mode: e.target.value as SimulationRequest['mode'] })}>
          <option value="auto">自动 · 根据观众调整</option><option value="paused">暂停</option><option value="idle">固定慢速</option><option value="online">固定实时</option><option value="fast_forward">快进指定步数</option>
        </select></Field>
        <div className="grid gap-4 sm:grid-cols-2"><Field label="实时模式间隔（秒）"><input className={fieldClass} type="number" required min="1" max="3600" value={simulation.tick_seconds_online} onChange={e => setSimulation({ ...simulation, tick_seconds_online: Number(e.target.value) })} /></Field>
          <Field label="慢速模式间隔（秒）"><input className={fieldClass} type="number" required min="1" max="86400" value={simulation.tick_seconds_idle} onChange={e => setSimulation({ ...simulation, tick_seconds_idle: Number(e.target.value) })} /></Field></div>
        {simulation.mode === 'fast_forward' && <Field label="快进步数（1–1000）"><input className={fieldClass} type="number" min="1" max="1000" required value={simulation.ticks} onChange={e => setSimulation({ ...simulation, ticks: Number(e.target.value) })} /></Field>}
        <button className="btn-primary" disabled={busy}>应用运行设置</button>
        <p className="text-xs text-muted">自动模式无人观看时约 5 秒一步；1 位观众按实时间隔运行，观众越多会逐步放慢，最多 180 秒一步。管理员固定模式会覆盖自动规则。</p>
      </form>
    </Section>
    <div className="space-y-6"><Section title="调整虚拟时间" description="跳到未来并暂停。跳过时段不会补算活动、对话或报告；需要完整模拟请使用快进。">
      <form className="space-y-4" onSubmit={e => { e.preventDefault(); const [h, m] = clock.split(':').map(Number); void run(() => adminApi.clock({ day, minute_of_day: h * 60 + m }), '已调整时间并暂停'); }}>
        <div className="grid grid-cols-2 gap-4"><Field label="虚拟日"><input className={fieldClass} type="number" min={overview.world.day} max="100000" required value={day} onChange={e => setDay(Number(e.target.value))} /></Field>
          <Field label="时刻（半小时对齐）"><input className={fieldClass} type="time" min="06:00" max="23:30" step="1800" required value={clock} onChange={e => setClock(e.target.value)} /></Field></div>
        <button className="btn-outline" disabled={busy}>跳转并暂停</button>
      </form></Section>
      <Section title="天气与自然环境" description="天气会影响室外活动选择。下一虚拟日由环境重新生成。">
        <form className="space-y-4" onSubmit={e => { e.preventDefault(); void run(() => adminApi.weather(weather), '天气已更新'); }}>
          <div className="grid grid-cols-2 gap-4"><Field label="天气"><select className={fieldClass} value={weather.kind} onChange={e => setWeather({ ...weather, kind: e.target.value as AdminWeatherRequest['kind'] })}>
            <option value="sunny">晴天</option><option value="cloudy">多云</option><option value="rainy">下雨</option><option value="foggy">有雾</option><option value="windy">大风</option>
          </select></Field><Field label="温度（℃）"><input className={fieldClass} type="number" min="-50" max="60" required value={weather.temp_c} onChange={e => setWeather({ ...weather, temp_c: Number(e.target.value) })} /></Field></div>
          <Field label="环境描述"><input className={fieldClass} maxLength={80} value={weather.text} onChange={e => setWeather({ ...weather, text: e.target.value })} placeholder="微风吹过湖面，适合散步" /></Field>
          <button className="btn-primary" disabled={busy}>更新天气</button>
        </form>
      </Section></div>
  </div>;
}
