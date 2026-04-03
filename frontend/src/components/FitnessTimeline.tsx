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
    <div className="w-full h-full p-4 flex flex-col" style={{ background: '#09090f' }}>
      <div className="text-xs font-semibold tracking-widest uppercase mb-3 whitespace-nowrap" style={{ color: 'rgba(255,255,255,0.35)' }}>
        Fitness Timeline
      </div>
      <div className="flex-1 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
            <XAxis 
              dataKey="generation" 
              stroke="rgba(255,255,255,0.4)" 
              tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 12 }} 
              domain={['dataMin', 'dataMax']}
            />
            <YAxis 
              stroke="rgba(255,255,255,0.4)" 
              tick={{ fill: 'rgba(255,255,255,0.4)', fontSize: 12 }}
              domain={[0, 1]}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#161622', borderColor: 'rgba(255,255,255,0.1)' }}
              itemStyle={{ color: '#fff' }}
            />
            <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
            <Line 
              type="monotone" 
              dataKey="best_fitness" 
              name="Best Fitness"
              stroke="#4edea3"
              strokeWidth={2}
              dot={false}
              animationDuration={500}
            />
            <Line 
              type="monotone" 
              dataKey="avg_fitness" 
              name="Avg Fitness"
              stroke="#adc6ff"
              strokeWidth={2}
              dot={false}
              animationDuration={500}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
