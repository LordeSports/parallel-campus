/** 心情曲线（spec/07 §3.5）：recharts LineChart。 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import type { MoodPointView } from '../api/types';

function tickLabel(tick: number) {
  const day = Math.floor(tick / 48) + 1;
  const m = ((tick - (day - 1) * 48) % 48) * 30 + 360;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

export default function MoodChart({ series }: { series: MoodPointView[] }) {
  if (series.length === 0) {
    return (
      <div className="grid h-40 place-items-center text-xs text-muted">今天还没有心情记录</div>
    );
  }

  const data = series.map((p) => ({
    tick: p.tick,
    label: tickLabel(p.tick),
    valence: Number(p.valence.toFixed(3)),
    arousal: Number(p.arousal.toFixed(3)),
  }));

  return (
    <div className="h-44 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="#00000010" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: '#6b7280' }}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis
            domain={[-1, 1]}
            ticks={[-1, -0.5, 0, 0.5, 1]}
            tick={{ fontSize: 10, fill: '#6b7280' }}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 10, border: '1px solid #00000010' }}
            formatter={(v: number, name: string) => [v, name === 'valence' ? '心情' : '活跃度']}
          />
          <Line
            type="monotone"
            dataKey="valence"
            stroke="#0084ff"
            strokeWidth={2}
            dot={{ r: 2 }}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
