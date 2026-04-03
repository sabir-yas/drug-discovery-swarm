import React, { useEffect, useRef } from 'react';

interface Props {
  sdfData: string | null;
}

export function MoleculeViewer3D({ sdfData }: Props) {
  const viewerRef = useRef<HTMLDivElement>(null);
  const viewerInstance = useRef<any>(null);

  useEffect(() => {
    if (!viewerRef.current) return;

    const render = () => {
      // @ts-ignore
      const $3Dmol = window.$3Dmol;
      if (!$3Dmol) return false;

      if (!viewerInstance.current) {
        viewerInstance.current = $3Dmol.createViewer(viewerRef.current, {
          backgroundColor: '#0c0c11'
        });
      }

      const viewer = viewerInstance.current;
      viewer.clear();
      if (sdfData) {
        viewer.addModel(sdfData, 'sdf');
        viewer.setStyle({}, { stick: { colorscheme: 'Jmol' } });
        viewer.zoomTo();
      }
      viewer.render();
      return true;
    };

    // Try immediately — if 3Dmol CDN hasn't loaded yet, poll every 100ms
    if (!render()) {
      const interval = setInterval(() => {
        if (render()) clearInterval(interval);
      }, 100);
      return () => clearInterval(interval);
    }
  }, [sdfData]);

  return (
    <div className="w-full h-full relative" style={{ minHeight: '300px' }}>
      <div className="absolute top-4 left-4 z-10 text-sm font-medium text-white/80 pointer-events-none">
        3D Conformer
      </div>
      {!sdfData && (
        <div className="absolute inset-0 flex items-center justify-center text-white/20 text-sm pointer-events-none">
          Select a molecule from the leaderboard to view
        </div>
      )}
      <div ref={viewerRef} className="w-full h-full" />
    </div>
  );
}
