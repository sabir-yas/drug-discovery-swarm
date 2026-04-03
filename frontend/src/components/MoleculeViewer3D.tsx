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
      <div className="absolute top-3 left-4 z-10 text-xs font-semibold tracking-widest uppercase pointer-events-none"
           style={{ color: 'rgba(255,255,255,0.35)' }}>
        3D Structure
      </div>

      {/* Loading spinner */}
      {loading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10"
             style={{ background: '#09090f' }}>
          <div className="w-6 h-6 rounded-full border-2 border-t-transparent animate-spin mb-2"
               style={{ borderColor: '#4edea3', borderTopColor: 'transparent' }} />
          <span className="text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>
            Computing conformer...
          </span>
        </div>
      )}

      {/* Empty state */}
      {!sdfData && !loading && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <span className="text-xs" style={{ color: 'rgba(255,255,255,0.18)' }}>
            Select a candidate to view 3D structure
          </span>
        </div>
      )}

      <div ref={viewerRef} className="w-full h-full" />
    </div>
  );
}
