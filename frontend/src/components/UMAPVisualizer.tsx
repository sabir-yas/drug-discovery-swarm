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
    <div ref={containerRef} className="w-full h-full relative" style={{ background: '#06080d' }}>
      {/* Top-left label */}
      <div style={{ position: 'absolute', top: 16, left: 16, zIndex: 10, pointerEvents: 'none' }}>
        <div style={{ fontSize: 9, letterSpacing: '0.18em', color: 'rgba(232,234,240,0.3)', fontWeight: 600, textTransform: 'uppercase', marginBottom: 2 }}>
          Chemical Space
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "'Space Grotesk',sans-serif", color: '#e8eaf0', lineHeight: 1, letterSpacing: '-0.02em' }}>
          {molecules.length.toLocaleString()}
        </div>
        <div style={{ fontSize: 9, color: 'rgba(232,234,240,0.25)', marginTop: 1 }}>molecules explored</div>
      </div>

      {/* Hover tooltip */}
      {tooltip && (
        <div style={{
          position: 'absolute', zIndex: 30, pointerEvents: 'none',
          left: tooltip.x + 14, top: tooltip.y - 60,
          background: 'rgba(16,19,26,0.95)', backdropFilter: 'blur(8px)',
          border: '1px solid rgba(161,255,194,0.15)', borderRadius: 8,
          padding: '7px 10px', fontSize: 10,
        }}>
          <div style={{ fontFamily: "'JetBrains Mono',monospace", color: '#e8eaf0', marginBottom: 3 }}>{tooltip.mol.id}</div>
          <div style={{ color: '#a1ffc2', fontFamily: "'JetBrains Mono',monospace" }}>fitness {tooltip.mol.fitness.toFixed(3)}</div>
          <div style={{ color: 'rgba(232,234,240,0.4)', marginTop: 1 }}>gen {tooltip.mol.generation} · click for 3D</div>
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
