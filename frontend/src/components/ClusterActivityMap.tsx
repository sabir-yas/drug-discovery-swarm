import React from 'react';
import { motion } from 'framer-motion';

interface AgentReport {
  agent_id: string;
  agent_type: string;
  activity: string;
  detail: string;
}

interface NodeActivity {
  node_id: string;
  hostname: string;
  cpu_total: number;
  cpu_used: number;
  utilization: number;
  status: 'active' | 'dead';
  agents: AgentReport[];
}

const AGENT_COLORS: Record<string, string> = {
  ExplorerAgent: '#adc6ff',
  ChemistAgent:  '#4edea3',
  SafetyAgent:   '#fbbf24',
  SelectorAgent: '#c4b5fd',
};

const AGENT_LABELS: Record<string, string> = {
  ExplorerAgent: 'EXP',
  ChemistAgent:  'CHM',
  SafetyAgent:   'SAF',
  SelectorAgent: 'SEL',
};

interface Props {
  nodes: NodeActivity[];
}

export function ClusterActivityMap({ nodes }: Props) {
  if (!nodes || nodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-xs tracking-widest uppercase" style={{ color: 'rgba(255,255,255,0.2)' }}>
        Awaiting cluster telemetry...
      </div>
    );
  }

  return (
    <div className="flex gap-2 px-4 py-3 h-full overflow-x-auto">
      {nodes.map((node) => {
        const pct = Math.round(node.utilization * 100);
        const barColor = node.utilization > 0.8 ? '#ef4444' : node.utilization > 0.5 ? '#fbbf24' : '#4edea3';

        return (
          <motion.div
            key={node.node_id}
            className="flex flex-col shrink-0 rounded-xl p-3 min-w-[160px]"
            style={{
              background: 'rgba(255,255,255,0.03)',
              border: `1px solid ${node.status === 'active' ? 'rgba(78,222,163,0.15)' : 'rgba(255,255,255,0.05)'}`,
              backdropFilter: 'blur(8px)',
            }}
            animate={{
              boxShadow: node.utilization > 0.4
                ? ['0 0 0px rgba(78,222,163,0)', '0 0 10px rgba(78,222,163,0.12)', '0 0 0px rgba(78,222,163,0)']
                : 'none',
            }}
            transition={{ repeat: Infinity, duration: 2.5 }}
          >
            {/* Node header */}
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-mono font-medium truncate" style={{ color: '#e8e6f0' }}>
                {node.hostname}
              </span>
              <span
                className="text-[9px] px-1.5 py-0.5 rounded-full font-medium ml-1 shrink-0"
                style={{
                  background: node.status === 'active' ? 'rgba(78,222,163,0.12)' : 'rgba(255,255,255,0.05)',
                  color:      node.status === 'active' ? '#4edea3' : 'rgba(255,255,255,0.3)',
                }}
              >
                {node.status === 'active' ? '● LIVE' : '○ IDLE'}
              </span>
            </div>

            {/* CPU bar */}
            <div className="h-1 w-full rounded-full mb-1 overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
              <motion.div
                className="h-full rounded-full"
                style={{ background: barColor }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.6, ease: 'easeOut' }}
              />
            </div>
            <div className="text-[10px] mb-2.5 font-mono" style={{ color: 'rgba(255,255,255,0.3)' }}>
              {pct}% CPU · {node.cpu_used}/{node.cpu_total} cores
            </div>

            {/* Agent tags */}
            <div className="flex flex-wrap gap-1">
              {node.agents.slice(0, 4).map((agent) => (
                <span
                  key={agent.agent_id}
                  className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                  style={{
                    background: `${AGENT_COLORS[agent.agent_type] ?? '#fff'}18`,
                    color:       AGENT_COLORS[agent.agent_type] ?? 'rgba(255,255,255,0.4)',
                    border:     `1px solid ${AGENT_COLORS[agent.agent_type] ?? '#fff'}30`,
                  }}
                >
                  {AGENT_LABELS[agent.agent_type] ?? 'AGT'}
                </span>
              ))}
              {node.agents.length === 0 && (
                <span className="text-[10px]" style={{ color: 'rgba(255,255,255,0.2)' }}>No active agents</span>
              )}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
