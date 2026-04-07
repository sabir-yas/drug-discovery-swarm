import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from 'recharts';

interface DataPoint {
  generation: number;
  best_fitness: number;
  avg_fitness: number;
}

interface Props {
  data: DataPoint[];
}

export function FitnessTimeline({ data }: Props) {
  return (
    <div className="w-full h-full px-4 pt-4 pb-2 flex flex-col" style={{ background: 'transparent' }}>
      <div className="text-[10px] font-semibold tracking-[0.18em] uppercase mb-3 whitespace-nowrap"
        style={{ color: 'rgba(232,234,240,0.38)', fontFamily: "'Inter', sans-serif" }}>
        Fitness Timeline
      </div>
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="rgba(232,234,240,0.06)" />
            <XAxis
              dataKey="generation"
              stroke="rgba(232,234,240,0.15)"
              tick={{ fill: 'rgba(232,234,240,0.3)', fontSize: 10, fontFamily: 'JetBrains Mono' }}
              domain={['dataMin', 'dataMax']}
            />
            <YAxis
              stroke="rgba(232,234,240,0.15)"
              tick={{ fill: 'rgba(232,234,240,0.3)', fontSize: 10, fontFamily: 'JetBrains Mono' }}
              domain={[0, 1]}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#141820', border: 'none', borderRadius: '8px', fontSize: 11 }}
              itemStyle={{ color: '#e8eaf0' }}
              labelStyle={{ color: 'rgba(232,234,240,0.5)', marginBottom: 4 }}
            />
            <Line
              type="monotone"
              dataKey="best_fitness"
              name="Best"
              stroke="#a1ffc2"
              strokeWidth={2}
              dot={false}
              animationDuration={400}
            />
            <Line
              type="monotone"
              dataKey="avg_fitness"
              name="Avg"
              stroke="#00e3fd"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              animationDuration={400}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
