import React, { useEffect, useRef } from 'react';

interface Props {
  sdfData: string | null;
  loading?: boolean;
}

export function MoleculeViewer3D({ sdfData, loading }: Props) {
  const viewerRef = useRef<HTMLDivElement>(null);
  const viewerInstance = useRef<any>(null);

  useEffect(() => {
    if (!viewerRef.current || loading) return;

    const render = () => {
      // @ts-ignore
      const $3Dmol = window.$3Dmol;
      if (!$3Dmol) return false;

      if (!viewerInstance.current) {
        viewerInstance.current = $3Dmol.createViewer(viewerRef.current, {
          backgroundColor: '#09090f'
        });
      }

      const viewer = viewerInstance.current;
      viewer.clear();
      if (sdfData) {
        viewer.addModel(sdfData, 'sdf');
        viewer.setStyle({}, { stick: { colorscheme: 'Jmol', radius: 0.15 }, sphere: { scale: 0.25 } });
        viewer.zoomTo();
      }
      viewer.render();
      return true;
    };

    if (!render()) {
      const interval = setInterval(() => {
        if (render()) clearInterval(interval);
      }, 100);
      return () => clearInterval(interval);
    }
  }, [sdfData, loading]);

  return (
    <div className="w-full h-full relative" style={{ minHeight: '200px' }}>
      {/* Header */}
      <div style={{ position: 'absolute', top: 10, left: 12, zIndex: 10, pointerEvents: 'none' }}>
        <div style={{ fontSize: 8, letterSpacing: '0.16em', color: 'rgba(232,234,240,0.3)', fontWeight: 600, textTransform: 'uppercase' }}>
          3D Structure
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', zIndex: 10, background: 'rgba(12,14,18,0.85)' }}>
          <div style={{ width: 20, height: 20, borderRadius: '50%', border: '2px solid #a1ffc2', borderTopColor: 'transparent', animation: 'spin 0.8s linear infinite', marginBottom: 8 }} />
          <span style={{ fontSize: 9, color: 'rgba(232,234,240,0.3)', letterSpacing: '0.1em' }}>Computing…</span>
        </div>
      )}

      {/* Empty */}
      {!sdfData && !loading && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none', gap: 6 }}>
          <div style={{ width: 28, height: 28, borderRadius: '50%', border: '1px solid rgba(161,255,194,0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'rgba(161,255,194,0.25)' }} />
          </div>
          <span style={{ fontSize: 9, color: 'rgba(232,234,240,0.2)', letterSpacing: '0.08em' }}>Select a molecule</span>
        </div>
      )}

      <div ref={viewerRef} className="w-full h-full" />
    </div>
  );
}
