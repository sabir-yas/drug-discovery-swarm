import React, { useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface AgentEvent {
  agent_type: string;
  agent_id: string;
  event_type: string;
  message: string;
  timestamp: number;
}

const AGENT_CONFIG: Record<string, { color: string; label: string; tag: string }> = {
  ExplorerAgent: { color: '#00e3fd', label: 'Explorer', tag: 'EXP' },
  ChemistAgent:  { color: '#a1ffc2', label: 'Chemist',  tag: 'CHM' },
  SafetyAgent:   { color: '#ffc563', label: 'Safety',   tag: 'SAF' },
  SelectorAgent: { color: '#c4b5fd', label: 'Selector', tag: 'SEL' },
};

export function AgentChatLog({ events }: { events: AgentEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto py-1"
      style={{ background: 'transparent', scrollBehavior: 'smooth' }}
    >
      {events.length === 0 && (
        <div className="text-center mt-8 text-[11px] tracking-widest uppercase" style={{ color: 'rgba(255,255,255,0.18)' }}>
          Awaiting signals...
        </div>
      )}
      <AnimatePresence initial={false}>
        {events.slice(-60).map((evt, i) => {
          const cfg = AGENT_CONFIG[evt.agent_type] ?? { color: '#888', label: 'Agent', tag: 'AGT' };
          const time = new Date(evt.timestamp * 1000).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });

          return (
            <motion.div
              key={`${evt.timestamp}-${evt.agent_id}-${i}`}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.15 }}
              className="flex items-start gap-2 py-1 px-3"
              style={{ background: 'transparent' }}
            >
              {/* Tag */}
              <span
                className="shrink-0 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded mt-0.5"
                style={{
                  background: `${cfg.color}15`,
                  color: cfg.color,
                  border: `1px solid ${cfg.color}25`,
                }}
              >
                {cfg.tag}
              </span>

              {/* Message */}
              <div className="flex-1 min-w-0">
                <span className="text-[11px] leading-snug break-words" style={{ color: 'rgba(255,255,255,0.7)' }}>
                  {evt.message}
                </span>
              </div>

              {/* Time */}
              <span className="shrink-0 text-[9px] font-mono mt-0.5" style={{ color: 'rgba(255,255,255,0.2)' }}>
                {time}
              </span>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
