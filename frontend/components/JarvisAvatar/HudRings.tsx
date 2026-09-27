"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { AvatarState } from "./useAvatarState";

export function HudRings({ state }: { state: AvatarState }) {
  const ring1 = useRef<THREE.Mesh>(null);
  const ring2 = useRef<THREE.Mesh>(null);

  const speed = state === "listening" ? 2.5 : state === "thinking" ? 4 : state === "speaking" ? 1.5 : 0.5;
  const color = state === "listening" ? "#3ddcff" : state === "thinking" ? "#ffd43d" : state === "speaking" ? "#4dff88" : "#3d6dff";

  useFrame((_, delta) => {
    if (ring1.current) ring1.current.rotation.z += delta * speed * 0.3;
    if (ring2.current) ring2.current.rotation.z -= delta * speed * 0.2;
  });

  return (
    <>
      <mesh ref={ring1} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.8, 0.01, 8, 100]} />
        <meshBasicMaterial color={color} transparent opacity={0.6} />
      </mesh>
      <mesh ref={ring2} rotation={[Math.PI / 2, 0.3, 0]}>
        <torusGeometry args={[2.1, 0.008, 8, 100]} />
        <meshBasicMaterial color={color} transparent opacity={0.4} />
      </mesh>
    </>
  );
}