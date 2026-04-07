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
  ExplorerAgent: '#00e3fd',
  ChemistAgent:  '#a1ffc2',
  SafetyAgent:   '#ffc563',
  SelectorAgent: '#c4b5fd',
};

const AGENT_LABELS: Record<string, string> = {
  ExplorerAgent: 'EXP',
  ChemistAgent:  'CHM',
  SafetyAgent:   'SAF',
  SelectorAgent: 'SEL',
};

export function ClusterActivityMap({ nodes }: { nodes: NodeActivity[] }) {
  if (!nodes || nodes.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', background: 'rgba(12,14,18,0.7)', backdropFilter: 'blur(8px)', borderRadius: 10, border: '1px solid rgba(232,234,240,0.06)', width: 'fit-content' }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'rgba(232,234,240,0.2)', display: 'inline-block' }} />
        <span style={{ fontSize: 9, color: 'rgba(232,234,240,0.3)', letterSpacing: '0.15em', fontWeight: 600, textTransform: 'uppercase' }}>Awaiting cluster telemetry</span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {nodes.map((node) => {
        const pct = Math.round(node.utilization * 100);
        const barColor = node.utilization > 0.8 ? '#ef4444' : node.utilization > 0.5 ? '#ffc563' : '#a1ffc2';

        return (
          <motion.div
            key={node.node_id}
            style={{
              background: 'rgba(12,14,18,0.82)',
              backdropFilter: 'blur(10px)',
              border: `1px solid ${node.status === 'active' ? 'rgba(161,255,194,0.18)' : 'rgba(232,234,240,0.06)'}`,
              borderRadius: 10,
              padding: '8px 12px',
              minWidth: 160,
            }}
            animate={{
              boxShadow: node.utilization > 0.3
                ? ['0 0 0px rgba(161,255,194,0)', '0 0 12px rgba(161,255,194,0.1)', '0 0 0px rgba(161,255,194,0)']
                : 'none',
            }}
            transition={{ repeat: Infinity, duration: 2.5 }}
          >
            {/* Node name + status */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontSize: 10, fontFamily: "'JetBrains Mono',monospace", color: '#e8eaf0', fontWeight: 600 }}>
                {node.hostname}
              </span>
              <span style={{
                fontSize: 8, padding: '1px 6px', borderRadius: 4, fontWeight: 700, letterSpacing: '0.08em',
                background: node.status === 'active' ? 'rgba(161,255,194,0.12)' : 'rgba(232,234,240,0.05)',
                color: node.status === 'active' ? '#a1ffc2' : 'rgba(232,234,240,0.25)',
              }}>
                {node.status === 'active' ? 'LIVE' : 'IDLE'}
              </span>
            </div>

            {/* CPU bar */}
            <div style={{ height: 2, background: 'rgba(232,234,240,0.07)', borderRadius: 2, marginBottom: 4, overflow: 'hidden' }}>
              <motion.div
                style={{ height: '100%', borderRadius: 2, background: barColor }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.6, ease: 'easeOut' }}
              />
            </div>
            <div style={{ fontSize: 9, color: 'rgba(232,234,240,0.3)', fontFamily: "'JetBrains Mono',monospace", marginBottom: 6 }}>
              {pct}% · {node.cpu_used}/{node.cpu_total} cores
            </div>

            {/* Agent tags */}
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {node.agents.slice(0, 4).map((agent) => {
                const c = AGENT_COLORS[agent.agent_type] ?? '#888';
                return (
                  <span key={agent.agent_id} style={{
                    fontSize: 8, padding: '1px 5px', borderRadius: 3, fontFamily: "'JetBrains Mono',monospace", fontWeight: 700,
                    background: `${c}18`, color: c, border: `1px solid ${c}28`,
                  }}>
                    {AGENT_LABELS[agent.agent_type] ?? 'AGT'}
                  </span>
                );
              })}
              {node.agents.length === 0 && (
                <span style={{ fontSize: 9, color: 'rgba(232,234,240,0.2)' }}>idle</span>
              )}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
