import { useState, useEffect, useCallback, useRef } from 'react';
import useWebSocketDefault, { ReadyState } from 'react-use-websocket';
const useWebSocket = typeof useWebSocketDefault === 'function'
  ? useWebSocketDefault : (useWebSocketDefault as any).default;

import { Play, Pause, Dna, WifiOff, Activity } from 'lucide-react';
import { ClusterActivityMap } from './components/ClusterActivityMap';
import { AgentChatLog } from './components/AgentChatLog';
import { UMAPVisualizer } from './components/UMAPVisualizer';
import { MoleculeViewer3D } from './components/MoleculeViewer3D';
import { FitnessTimeline } from './components/FitnessTimeline';

const BACKEND_HOST = import.meta.env.VITE_BACKEND_HOST ?? 'localhost:8000';
const WS_URL  = `ws://${BACKEND_HOST}/ws`;
const API_URL = `http://${BACKEND_HOST}/api`;

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 520;
const BOTTOM_MIN  = 100;
const BOTTOM_MAX  = 420;

function useDrag(
  initial: number,
  min: number,
  max: number,
  direction: 'horizontal' | 'vertical',
  invert: boolean = false,
) {
  const [size, setSize] = useState(initial);
  const dragging = useRef(false);
  const startPos = useRef(0);
  const startSize = useRef(initial);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    startPos.current  = direction === 'horizontal' ? e.clientX : e.clientY;
    startSize.current = size;

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const delta = (direction === 'horizontal' ? ev.clientX : ev.clientY) - startPos.current;
      const next  = invert ? startSize.current - delta : startSize.current + delta;
      setSize(Math.min(max, Math.max(min, next)));
    };
    const onUp = () => {
      dragging.current = false;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [size, min, max, direction, invert]);

  return { size, onMouseDown };
}

export default function App() {
  const [state, setState] = useState({
    generation: 0, totalMolecules: 0, isRunning: false, isPaused: false,
    clusterNodes: [] as any[], agentEvents: [] as any[],
    molecules: [] as any[], leaderboard: [] as any[], timelineData: [] as any[],
    bestFitness: 0, avgFitness: 0, numSafe: 0,
  });
  const [selectedSdf,   setSelectedSdf]   = useState<string | null>(null);
  const [selectedMolId, setSelectedMolId] = useState<string | null>(null);
  const [loadingMol,    setLoadingMol]    = useState(false);

  // Resizable panels
  const sidebar = useDrag(300, SIDEBAR_MIN, SIDEBAR_MAX, 'horizontal', true);
  const bottom  = useDrag(200, BOTTOM_MIN,  BOTTOM_MAX,  'vertical',   true);

  const { sendMessage, lastMessage, readyState } = useWebSocket(WS_URL, {
    shouldReconnect: () => true, reconnectAttempts: 10, reconnectInterval: 3000,
  });
  const connected = readyState === ReadyState.OPEN;

  useEffect(() => {
    if (!lastMessage) return;
    try {
      const d = JSON.parse(lastMessage.data);
      if (d.type === 'generation_update') {
        setState(p => ({ ...p, clusterNodes: d.cluster_activity || p.clusterNodes, agentEvents: d.agent_events || p.agentEvents }));
      } else if (d.type === 'generation_complete') {
        setState(p => ({
          ...p,
          generation: d.generation, totalMolecules: d.total_explored,
          bestFitness: d.best_fitness ?? p.bestFitness, avgFitness: d.avg_fitness ?? p.avgFitness,
          numSafe: d.num_safe ?? p.numSafe,
          clusterNodes: d.cluster_activity || p.clusterNodes, agentEvents: d.agent_events || p.agentEvents,
          leaderboard: d.leaderboard || p.leaderboard, molecules: d.molecules || p.molecules,
          timelineData: [...p.timelineData, { generation: d.generation, avg_fitness: d.avg_fitness, best_fitness: d.best_fitness }],
        }));
      }
    } catch {}
  }, [lastMessage]);

  const fetchMolecule3D = useCallback(async (molId: string) => {
    if (loadingMol) return;
    setLoadingMol(true); setSelectedMolId(molId);
    try {
      const res = await fetch(`${API_URL}/molecule/${molId}`);
      if (res.ok) { const d = await res.json(); if (d?.sdf) setSelectedSdf(d.sdf); }
    } catch {} finally { setLoadingMol(false); }
  }, [loadingMol]);

  const handleStart = () => { sendMessage(JSON.stringify({ action: 'start' })); setState(p => ({ ...p, isRunning: true, isPaused: false })); };
  const handlePauseResume = () => {
    const action = state.isPaused ? 'resume' : 'pause';
    sendMessage(JSON.stringify({ action })); setState(p => ({ ...p, isPaused: !p.isPaused }));
  };

  const rankColor = (i: number) => i === 0 ? '#ffc563' : i === 1 ? '#b8c4d4' : i === 2 ? '#cd7c2f' : 'rgba(232,234,240,0.25)';

  const HEADER_H = 52;
  const bodyH = `calc(100vh - ${HEADER_H}px)`;

  return (
    <div className="h-screen w-screen overflow-hidden" style={{ background: '#0c0e12', color: '#e8eaf0', fontFamily: "'Inter',sans-serif" }}>

      {/* ═══ HEADER ═══ */}
      <header style={{ height: HEADER_H, background: '#10131a', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', position: 'relative', zIndex: 50 }}>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: 10, background: 'rgba(161,255,194,0.12)', border: '1px solid rgba(161,255,194,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Dna size={16} color="#a1ffc2" />
          </div>
          <div>
            <div style={{ fontSize: 9, letterSpacing: '0.18em', color: 'rgba(232,234,240,0.35)', fontWeight: 600, textTransform: 'uppercase' }}>Autonomous Drug Discovery</div>
            <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: '-0.02em', fontFamily: "'Space Grotesk',sans-serif", lineHeight: 1.1 }}>Swarm Mission Control</div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 2, background: '#0c0e12', borderRadius: 12, padding: '4px 6px', border: '1px solid rgba(232,234,240,0.07)' }}>
          {[
            { label: 'GEN',       value: String(state.generation),                color: '#a1ffc2' },
            { label: 'MOLECULES', value: state.totalMolecules.toLocaleString(),    color: '#00e3fd' },
            { label: 'BEST',      value: state.bestFitness.toFixed(3),             color: '#ffc563' },
            { label: 'AVG',       value: state.avgFitness.toFixed(3),              color: 'rgba(232,234,240,0.5)' },
            { label: 'SAFE',      value: String(state.numSafe),                    color: '#a1ffc2' },
          ].map(({ label, value, color }, i) => (
            <div key={label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3px 12px', borderRight: i < 4 ? '1px solid rgba(232,234,240,0.06)' : 'none' }}>
              <span style={{ fontSize: 8, letterSpacing: '0.15em', color: 'rgba(232,234,240,0.3)', fontWeight: 600 }}>{label}</span>
              <span style={{ fontSize: 14, fontWeight: 700, color, fontFamily: "'JetBrains Mono',monospace", lineHeight: 1.2 }}>{value}</span>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 600, letterSpacing: '0.1em', color: connected ? '#a1ffc2' : '#ef4444' }}>
            {connected
              ? <><span style={{ width: 6, height: 6, borderRadius: '50%', background: '#a1ffc2', display: 'inline-block', animation: 'pulse 2s infinite' }} />LIVE</>
              : <><WifiOff size={10} />OFFLINE</>
            }
          </div>

          {!state.isRunning ? (
            <button onClick={handleStart} disabled={!connected}
              style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '7px 18px', borderRadius: 10, background: '#a1ffc2', color: '#0c0e12', fontSize: 12, fontWeight: 700, fontFamily: "'Space Grotesk',sans-serif", border: 'none', cursor: connected ? 'pointer' : 'not-allowed', opacity: connected ? 1 : 0.35, letterSpacing: '0.01em' }}>
              <Play size={12} fill="#0c0e12" /> Launch Swarm
            </button>
          ) : (
            <button onClick={handlePauseResume}
              style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '7px 18px', borderRadius: 10, background: 'rgba(232,234,240,0.07)', color: '#e8eaf0', fontSize: 12, fontWeight: 600, border: '1px solid rgba(232,234,240,0.1)', cursor: 'pointer' }}>
              {state.isPaused ? <Play size={12} /> : <Pause size={12} />}
              {state.isPaused ? 'Resume' : 'Pause'}
            </button>
          )}
        </div>
      </header>

      {/* ═══ BODY ═══ */}
      <div style={{ height: bodyH, display: 'flex', flexDirection: 'row', overflow: 'hidden' }}>

        {/* ── LEFT COLUMN: UMAP + bottom row ── */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* UMAP hero */}
          <div style={{ flex: 1, minHeight: 0, position: 'relative', background: '#06080d', overflow: 'hidden' }}>
            <UMAPVisualizer molecules={state.molecules} onSelect={fetchMolecule3D} />

            {/* Floating cluster nodes — bottom-left */}
            <div style={{ position: 'absolute', bottom: 16, left: 16, zIndex: 10, pointerEvents: 'none' }}>
              <ClusterActivityMap nodes={state.clusterNodes} />
            </div>

            {/* Floating 3D viewer — top-right */}
            <div style={{
              position: 'absolute', top: 16, right: 16, width: 260, height: 240, zIndex: 20,
              background: 'rgba(16,19,26,0.85)', backdropFilter: 'blur(12px)',
              borderRadius: 14, border: '1px solid rgba(161,255,194,0.12)',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)', overflow: 'hidden',
            }}>
              <MoleculeViewer3D sdfData={selectedSdf} loading={loadingMol} />
            </div>
          </div>

          {/* Horizontal drag handle (bottom row height) */}
          <div
            onMouseDown={bottom.onMouseDown}
            style={{
              height: 4, cursor: 'row-resize', flexShrink: 0,
              background: 'transparent', position: 'relative', zIndex: 30,
            }}
          >
            <div style={{ position: 'absolute', inset: '1px 0', background: 'rgba(232,234,240,0.06)', transition: 'background 0.15s' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,227,253,0.25)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'rgba(232,234,240,0.06)')}
            />
          </div>

          {/* Fitness Timeline — resizable height */}
          <div style={{ height: bottom.size, flexShrink: 0, background: '#0e1016', borderTop: '1px solid rgba(232,234,240,0.05)', overflow: 'hidden' }}>
            <FitnessTimeline data={state.timelineData} />
          </div>
        </div>

        {/* Vertical drag handle (sidebar width) */}
        <div
          onMouseDown={sidebar.onMouseDown}
          style={{
            width: 4, cursor: 'col-resize', flexShrink: 0,
            background: 'transparent', position: 'relative', zIndex: 30,
          }}
        >
          <div style={{ position: 'absolute', inset: '0 1px', background: 'rgba(232,234,240,0.06)', transition: 'background 0.15s' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,227,253,0.25)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'rgba(232,234,240,0.06)')}
          />
        </div>

        {/* ── RIGHT COLUMN: Candidates + Agent Log ── */}
        <div style={{ width: sidebar.size, flexShrink: 0, display: 'flex', flexDirection: 'column', background: '#10131a', overflow: 'hidden' }}>

          {/* Top Candidates */}
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', borderLeft: '1px solid rgba(232,234,240,0.05)' }}>
            <div style={{ padding: '14px 16px 10px', borderBottom: '1px solid rgba(232,234,240,0.05)', flexShrink: 0 }}>
              <div style={{ fontSize: 9, letterSpacing: '0.18em', color: 'rgba(232,234,240,0.35)', fontWeight: 600, textTransform: 'uppercase', marginBottom: 2 }}>Top Candidates</div>
              <div style={{ fontSize: 10, color: 'rgba(232,234,240,0.2)' }}>
                {state.leaderboard.length > 0 ? `${state.leaderboard.length} ranked · click to view 3D` : 'Awaiting first generation…'}
              </div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto' }}>
              {state.leaderboard.map((mol: any, idx: number) => {
                const isSelected = selectedMolId === mol.id;
                return (
                  <button key={mol.id} onClick={() => fetchMolecule3D(mol.id)}
                    style={{
                      width: '100%', textAlign: 'left', padding: '10px 14px',
                      background: isSelected ? 'rgba(161,255,194,0.06)' : 'transparent',
                      borderLeft: isSelected ? '2px solid #a1ffc2' : '2px solid transparent',
                      borderBottom: '1px solid rgba(232,234,240,0.04)',
                      cursor: 'pointer', transition: 'background 0.15s', display: 'block',
                    }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                      <span style={{ fontSize: 11, fontWeight: 800, color: rankColor(idx), fontFamily: "'JetBrains Mono',monospace", minWidth: 16, paddingTop: 1 }}>
                        {idx + 1}
                      </span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 10, fontFamily: "'JetBrains Mono',monospace", color: '#e8eaf0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {mol.id}
                        </div>
                        <div style={{ fontSize: 8, color: 'rgba(232,234,240,0.3)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {mol.smiles}
                        </div>
                        <div style={{ marginTop: 5, height: 2, borderRadius: 2, background: 'rgba(232,234,240,0.07)' }}>
                          <div style={{ height: '100%', borderRadius: 2, width: `${mol.fitness * 100}%`, background: 'linear-gradient(90deg, #a1ffc2, #00e3fd)', transition: 'width 0.5s' }} />
                        </div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                          <span style={{ fontSize: 8, color: 'rgba(232,234,240,0.3)' }}>bind <span style={{ color: '#a1ffc2' }}>{mol.binding_score?.toFixed(2) ?? '—'}</span></span>
                          <span style={{ fontSize: 8, color: 'rgba(232,234,240,0.3)' }}>DL <span style={{ color: '#00e3fd' }}>{mol.drug_likeness?.toFixed(2) ?? '—'}</span></span>
                          {mol.sa_score != null && (
                            <span style={{ fontSize: 8, color: 'rgba(232,234,240,0.3)' }}>SA <span style={{ color: mol.sa_score <= 3 ? '#a1ffc2' : mol.sa_score <= 6 ? '#ffc563' : '#ef4444' }}>{mol.sa_score.toFixed(1)}</span></span>
                          )}
                          {mol.vina_affinity_kcal != null && (
                            <span style={{ fontSize: 8, color: '#ffc563', fontFamily: "'JetBrains Mono',monospace" }}>ΔG {mol.vina_affinity_kcal.toFixed(1)}</span>
                          )}
                        </div>
                      </div>
                      <span style={{ fontSize: 13, fontWeight: 700, color: '#a1ffc2', fontFamily: "'JetBrains Mono',monospace", flexShrink: 0, paddingTop: 1 }}>
                        {mol.fitness.toFixed(3)}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Horizontal drag handle between candidates and log */}
          <div
            onMouseDown={bottom.onMouseDown}
            style={{ height: 4, cursor: 'row-resize', flexShrink: 0, background: 'transparent', position: 'relative', zIndex: 30 }}
          >
            <div style={{ position: 'absolute', inset: '1px 0', background: 'rgba(232,234,240,0.06)', transition: 'background 0.15s' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,227,253,0.25)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'rgba(232,234,240,0.06)')}
            />
          </div>

          {/* Agent Log — synced bottom height */}
          <div style={{ height: bottom.size, flexShrink: 0, background: '#0c0f15', borderTop: '1px solid rgba(232,234,240,0.05)', borderLeft: '1px solid rgba(232,234,240,0.05)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ padding: '10px 14px 6px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Activity size={10} color="rgba(232,234,240,0.3)" />
                <span style={{ fontSize: 9, letterSpacing: '0.15em', color: 'rgba(232,234,240,0.3)', fontWeight: 600, textTransform: 'uppercase' }}>Network Logs</span>
              </div>
              {state.isRunning && (
                <span style={{ fontSize: 8, color: '#a1ffc2', letterSpacing: '0.12em', fontWeight: 600 }}>● LIVE</span>
              )}
            </div>
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <AgentChatLog events={state.agentEvents} />
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
        button:hover { filter: brightness(1.08); }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(232,234,240,0.1); border-radius: 2px; }
      `}</style>
    </div>
  );
}
