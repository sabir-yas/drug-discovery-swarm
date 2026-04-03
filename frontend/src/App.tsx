import { useState, useEffect, useCallback } from 'react';
import useWebSocketDefault, { ReadyState } from 'react-use-websocket';

const useWebSocket = typeof useWebSocketDefault === 'function'
  ? useWebSocketDefault
  : (useWebSocketDefault as any).default;

import { Play, Pause, Telescope, Cpu, FlaskConical, Activity, Dna, Wifi, WifiOff } from 'lucide-react';
import { ClusterActivityMap } from './components/ClusterActivityMap';
import { AgentChatLog } from './components/AgentChatLog';
import { UMAPVisualizer } from './components/UMAPVisualizer';
import { MoleculeViewer3D } from './components/MoleculeViewer3D';
import { FitnessTimeline } from './components/FitnessTimeline';

const BACKEND_HOST = import.meta.env.VITE_BACKEND_HOST ?? 'localhost:8000';
const WS_URL  = `ws://${BACKEND_HOST}/ws`;
const API_URL = `http://${BACKEND_HOST}/api`;

const NAV_ITEMS = [
  { id: 'observatory',   label: 'Observatory',       icon: Telescope },
  { id: 'swarm',         label: 'Swarm Intelligence', icon: Cpu },
  { id: 'docking',       label: 'Molecular Docking',  icon: FlaskConical },
  { id: 'telemetry',     label: 'Kinetic Telemetry',  icon: Activity },
];

export default function App() {
  const [activeNav, setActiveNav] = useState('observatory');
  const [state, setState] = useState({
    generation: 0,
    totalMolecules: 0,
    isRunning: false,
    isPaused: false,
    clusterNodes: [] as any[],
    agentEvents: [] as any[],
    molecules: [] as any[],
    leaderboard: [] as any[],
    timelineData: [] as any[],
  });
  const [selectedSdf, setSelectedSdf] = useState<string | null>(null);
  const [selectedMolId, setSelectedMolId] = useState<string | null>(null);
  const [loadingMol, setLoadingMol] = useState(false);

  const { sendMessage, lastMessage, readyState } = useWebSocket(WS_URL, {
    shouldReconnect: () => true,
    reconnectAttempts: 10,
    reconnectInterval: 3000,
  });

  const connected = readyState === ReadyState.OPEN;

  useEffect(() => {
    if (!lastMessage) return;
    try {
      const data = JSON.parse(lastMessage.data);
      if (data.type === 'generation_update') {
        setState(prev => ({
          ...prev,
          clusterNodes: data.cluster_activity || prev.clusterNodes,
          agentEvents:  data.agent_events   || prev.agentEvents,
        }));
      } else if (data.type === 'generation_complete') {
        setState(prev => ({
          ...prev,
          generation:     data.generation,
          totalMolecules: data.total_explored,
          clusterNodes:   data.cluster_activity || prev.clusterNodes,
          agentEvents:    data.agent_events     || prev.agentEvents,
          leaderboard:    data.leaderboard      || prev.leaderboard,
          molecules:      data.molecules        || prev.molecules,
          timelineData:   [...prev.timelineData, {
            generation:   data.generation,
            avg_fitness:  data.avg_fitness,
            best_fitness: data.best_fitness,
          }],
        }));
      }
    } catch {}
  }, [lastMessage]);

  const fetchMolecule3D = useCallback(async (molId: string) => {
    if (loadingMol) return;
    setLoadingMol(true);
    setSelectedMolId(molId);
    try {
      const res = await fetch(`${API_URL}/molecule/${molId}`);
      if (res.ok) {
        const data = await res.json();
        if (data?.sdf) setSelectedSdf(data.sdf);
      }
    } catch {}
    finally { setLoadingMol(false); }
  }, [loadingMol]);

  const handleStart = () => {
    sendMessage(JSON.stringify({ action: 'start' }));
    setState(prev => ({ ...prev, isRunning: true, isPaused: false }));
  };

  const handlePauseResume = () => {
    const action = state.isPaused ? 'resume' : 'pause';
    sendMessage(JSON.stringify({ action }));
    setState(prev => ({ ...prev, isPaused: !prev.isPaused }));
  };

  return (
    <div
      className="h-screen w-screen flex overflow-hidden font-sans"
      style={{ background: '#08080f', color: '#e8e6f0' }}
    >
      {/* ── Left Sidebar Navigation ── */}
      <aside
        className="w-16 flex flex-col items-center py-5 gap-2 shrink-0 z-20"
        style={{ background: '#0a0914', borderRight: '1px solid rgba(255,255,255,0.04)' }}
      >
        {/* Logo */}
        <div className="mb-4 p-2 rounded-xl" style={{ background: 'rgba(78,222,163,0.12)' }}>
          <Dna size={20} style={{ color: '#4edea3' }} />
        </div>

        {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            title={label}
            onClick={() => setActiveNav(id)}
            className="w-10 h-10 flex items-center justify-center rounded-xl transition-all duration-200 group relative"
            style={{
              background:   activeNav === id ? 'rgba(78,222,163,0.15)' : 'transparent',
              color:        activeNav === id ? '#4edea3' : 'rgba(255,255,255,0.3)',
              border:       activeNav === id ? '1px solid rgba(78,222,163,0.25)' : '1px solid transparent',
            }}
          >
            <Icon size={18} />
            {/* Tooltip */}
            <span
              className="absolute left-14 px-2 py-1 rounded text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50"
              style={{ background: '#1a1925', color: '#e8e6f0', border: '1px solid rgba(255,255,255,0.08)' }}
            >
              {label}
            </span>
          </button>
        ))}
      </aside>

      {/* ── Main Area ── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* ── Top Header ── */}
        <header
          className="h-14 flex items-center justify-between px-5 shrink-0"
          style={{ background: '#0a0914', borderBottom: '1px solid rgba(255,255,255,0.04)' }}
        >
          {/* Left: title + status */}
          <div className="flex items-center gap-3">
            <div>
              <div className="text-xs font-semibold tracking-widest uppercase" style={{ color: 'rgba(255,255,255,0.35)' }}>
                AI Drug Discovery
              </div>
              <div className="text-sm font-semibold leading-tight" style={{ color: '#e8e6f0' }}>
                Swarm Mission Control
              </div>
            </div>
            {/* Connection pill */}
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
              style={{
                background: connected ? 'rgba(78,222,163,0.1)'  : 'rgba(239,68,68,0.1)',
                border:     connected ? '1px solid rgba(78,222,163,0.25)' : '1px solid rgba(239,68,68,0.25)',
                color:      connected ? '#4edea3' : '#ef4444',
              }}
            >
              {connected
                ? <><span className="w-1.5 h-1.5 rounded-full bg-[#4edea3] animate-pulse" />SWARM ACTIVE</>
                : <><WifiOff size={10} />OFFLINE</>
              }
            </div>
          </div>

          {/* Center: stats */}
          <div className="flex items-center gap-6">
            {[
              { label: 'GENERATION', value: state.generation },
              { label: 'MOLECULES',  value: state.totalMolecules.toLocaleString() },
            ].map(({ label, value }) => (
              <div key={label} className="flex flex-col items-center">
                <span className="text-[10px] tracking-widest font-medium" style={{ color: 'rgba(255,255,255,0.3)' }}>
                  {label}
                </span>
                <span className="text-xl font-mono font-semibold leading-none" style={{ color: '#4edea3' }}>
                  {value}
                </span>
              </div>
            ))}
          </div>

          {/* Right: action button */}
          <div>
            {!state.isRunning ? (
              <button
                onClick={handleStart}
                disabled={!connected}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all duration-200 disabled:opacity-40"
                style={{ background: 'rgba(78,222,163,0.9)', color: '#08080f' }}
              >
                <Play size={14} fill="currentColor" />
                Launch Swarm
              </button>
            ) : (
              <button
                onClick={handlePauseResume}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200"
                style={{ background: 'rgba(255,255,255,0.06)', color: '#e8e6f0', border: '1px solid rgba(255,255,255,0.08)' }}
              >
                {state.isPaused ? <Play size={14} /> : <Pause size={14} />}
                {state.isPaused ? 'Resume' : 'Pause'}
              </button>
            )}
          </div>
        </header>

        {/* ── Cluster Nodes Strip ── */}
        <div
          className="h-32 shrink-0 overflow-hidden"
          style={{ background: '#09090f', borderBottom: '1px solid rgba(255,255,255,0.04)' }}
        >
          <ClusterActivityMap nodes={state.clusterNodes} />
        </div>

        {/* ── Main Visualization Grid ── */}
        <div className="flex-1 grid min-h-0" style={{ gridTemplateColumns: '42% 33% 25%', gap: '1px', background: 'rgba(255,255,255,0.03)' }}>

          {/* UMAP — Chemical Space */}
          <div className="row-span-2 min-h-0 relative" style={{ background: '#08080f' }}>
            <UMAPVisualizer molecules={state.molecules} onSelect={fetchMolecule3D} />
          </div>

          {/* 3D Conformer */}
          <div className="min-h-0 relative" style={{ background: '#09090f' }}>
            <MoleculeViewer3D sdfData={selectedSdf} loading={loadingMol} />
          </div>

          {/* Fitness Timeline */}
          <div
            className="row-span-2 flex flex-col min-h-0"
            style={{ background: '#09090f', gridRow: '1 / 3', gridColumn: '3' }}
          >
            {/* Top Candidates */}
            <div className="h-1/2 flex flex-col min-h-0" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <div
                className="px-4 py-3 text-xs font-semibold tracking-widest uppercase shrink-0"
                style={{ color: 'rgba(255,255,255,0.35)', borderBottom: '1px solid rgba(255,255,255,0.04)' }}
              >
                Top Candidates
              </div>
              <div className="flex-1 overflow-y-auto py-1">
                {state.leaderboard.length === 0 && (
                  <div className="text-center mt-6 text-xs" style={{ color: 'rgba(255,255,255,0.2)' }}>
                    Awaiting first generation...
                  </div>
                )}
                {state.leaderboard.map((mol: any, idx: number) => (
                  <button
                    key={mol.id}
                    onClick={() => fetchMolecule3D(mol.id)}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition-all duration-150"
                    style={{
                      background: selectedMolId === mol.id ? 'rgba(78,222,163,0.08)' : 'transparent',
                      borderLeft: selectedMolId === mol.id ? '2px solid #4edea3' : '2px solid transparent',
                    }}
                    onMouseEnter={e => { if (selectedMolId !== mol.id) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)'; }}
                    onMouseLeave={e => { if (selectedMolId !== mol.id) (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                  >
                    <span
                      className="w-5 text-xs font-mono font-bold shrink-0"
                      style={{ color: idx === 0 ? '#fbbf24' : idx === 1 ? '#94a3b8' : idx === 2 ? '#cd7c2f' : 'rgba(255,255,255,0.25)' }}
                    >
                      {idx + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono truncate" style={{ color: '#e8e6f0' }}>{mol.id}</div>
                      <div className="text-[10px] truncate mt-0.5" style={{ color: 'rgba(255,255,255,0.25)' }}>{mol.smiles}</div>
                    </div>
                    <span className="text-xs font-semibold font-mono shrink-0" style={{ color: '#4edea3' }}>
                      {mol.fitness.toFixed(3)}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Agent Log */}
            <div className="h-1/2 flex flex-col min-h-0">
              <div
                className="px-4 py-3 flex items-center justify-between shrink-0"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
              >
                <span className="text-xs font-semibold tracking-widest uppercase" style={{ color: 'rgba(255,255,255,0.35)' }}>
                  Swarm Network Logs
                </span>
                {state.isRunning && (
                  <span className="flex gap-1 items-center">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#4edea3] animate-ping absolute" />
                    <span className="w-1.5 h-1.5 rounded-full bg-[#4edea3] relative" />
                  </span>
                )}
              </div>
              <div className="flex-1 overflow-hidden min-h-0">
                <AgentChatLog events={state.agentEvents} />
              </div>
            </div>
          </div>

          {/* Fitness Timeline */}
          <div className="min-h-0" style={{ background: '#09090f', borderTop: '1px solid rgba(255,255,255,0.03)' }}>
            <FitnessTimeline data={state.timelineData} />
          </div>

        </div>
      </div>
    </div>
  );
}
