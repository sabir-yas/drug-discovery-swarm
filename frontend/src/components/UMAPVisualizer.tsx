import React, { useMemo, useState, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Stars } from '@react-three/drei';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';

interface Molecule {
  id: string;
  umap_x: number;
  umap_y: number;
  umap_z: number;
  fitness: number;
  generation: number;
}

interface Tooltip {
  mol: Molecule;
  x: number;
  y: number;
}

interface Props {
  molecules: Molecule[];
  onSelect?: (id: string) => void;
}

export function UMAPVisualizer({ molecules, onSelect }: Props) {
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);
  const [isHovering, setIsHovering] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const orbitRef = useRef<OrbitControlsImpl>(null);

  const { positions, colors } = useMemo(() => {
    const pos = new Float32Array(molecules.length * 3);
    const col = new Float32Array(molecules.length * 3);
    const colorObj = new THREE.Color();

    molecules.forEach((m, i) => {
      pos[i * 3]     = m.umap_x * 10;
      pos[i * 3 + 1] = m.umap_y * 10;
      pos[i * 3 + 2] = m.umap_z * 10;

      // Blue (low fitness) → green (high fitness)
      colorObj.setHSL((1.0 - Math.min(1.0, m.fitness)) * 0.6, 0.8, 0.6);
      col[i * 3]     = colorObj.r;
      col[i * 3 + 1] = colorObj.g;
      col[i * 3 + 2] = colorObj.b;
    });

    return { positions: pos, colors: col };
  }, [molecules]);

  const handlePointerOver = (e: any) => {
    e.stopPropagation();
    document.body.style.cursor = 'pointer';
    setIsHovering(true);
    if (e.index !== undefined && molecules[e.index]) {
      const rect = containerRef.current?.getBoundingClientRect();
      const x = e.nativeEvent.clientX - (rect?.left ?? 0);
      const y = e.nativeEvent.clientY - (rect?.top ?? 0);
      setTooltip({ mol: molecules[e.index], x, y });
    }
  };

  const handlePointerMove = (e: any) => {
    if (e.index !== undefined && molecules[e.index]) {
      const rect = containerRef.current?.getBoundingClientRect();
      const x = e.nativeEvent.clientX - (rect?.left ?? 0);
      const y = e.nativeEvent.clientY - (rect?.top ?? 0);
      setTooltip({ mol: molecules[e.index], x, y });
    }
  };

  const handlePointerOut = () => {
    document.body.style.cursor = 'default';
    setIsHovering(false);
    setTooltip(null);
  };

  const handleClick = (e: any) => {
    e.stopPropagation();
    if (e.index !== undefined && onSelect && molecules[e.index]) {
      onSelect(molecules[e.index].id);
    }
  };

  return (
    <div ref={containerRef} className="w-full h-full bg-[#050508] relative">
      <div className="absolute top-4 left-4 z-10 font-medium text-white/80 pointer-events-none">
        Chemical Space (UMAP)
        <div className="text-xs text-white/40 mt-1">{molecules.length} molecules explored</div>
      </div>

      {/* Hover tooltip */}
      {tooltip && (
        <div
          className="absolute z-20 pointer-events-none bg-[#161622]/90 border border-white/10 rounded px-2 py-1.5 text-xs"
          style={{ left: tooltip.x + 12, top: tooltip.y - 40 }}
        >
          <div className="font-mono text-white">{tooltip.mol.id}</div>
          <div className="text-emerald-400">fitness: {tooltip.mol.fitness.toFixed(3)}</div>
          <div className="text-white/40">gen {tooltip.mol.generation}</div>
          <div className="text-white/30 mt-0.5">click to view 3D</div>
        </div>
      )}

      <Canvas
        camera={{ position: [0, 0, 50], fov: 60 }}
        raycaster={{ params: { Points: { threshold: 0.8 } } }}
      >
        <color attach="background" args={['#08080f']} />
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} />
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade speed={1} />
        <OrbitControls
          ref={orbitRef}
          enablePan
          enableZoom
          enableRotate
          autoRotate={!isHovering}
          autoRotateSpeed={0.4}
        />

        {molecules.length > 0 && (
          <points
            onClick={handleClick}
            onPointerOver={handlePointerOver}
            onPointerMove={handlePointerMove}
            onPointerOut={handlePointerOut}
          >
            <bufferGeometry>
              <bufferAttribute attach="attributes-position" args={[positions, 3]} />
              <bufferAttribute attach="attributes-color"    args={[colors, 3]} />
            </bufferGeometry>
            <pointsMaterial
              size={0.9}
              vertexColors
              transparent
              opacity={0.85}
              sizeAttenuation
            />
          </points>
        )}
      </Canvas>
    </div>
  );
}
