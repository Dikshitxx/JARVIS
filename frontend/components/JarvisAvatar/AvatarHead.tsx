"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { AvatarState } from "./useAvatarState";
import { useFakeSpeech } from "./useFakeSpeech";

export function AvatarHead({ state }: { state: AvatarState }) {
  const { scene } = useGLTF("/models/vitruvian_head.glb");
  const headMeshRef = useRef<THREE.Mesh | null>(null);
  const [ready, setReady] = useState(false);
  const blinkTimer = useRef(0);
  const blinkTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.morphTargetDictionary && obj.name === "cm_vitruvian") {
        headMeshRef.current = mesh;
        setReady(true);
      }
    });

    return () => {
      if (blinkTimeout.current) clearTimeout(blinkTimeout.current);
    };
  }, [scene]);

  const setMorph = useCallback((name: string, value: number) => {
    const mesh = headMeshRef.current;
    if (!mesh?.morphTargetDictionary || !mesh.morphTargetInfluences) return;
    const idx = mesh.morphTargetDictionary[name];
    if (idx !== undefined) mesh.morphTargetInfluences[idx] = value;
  }, []);

  const resetMorphs = useCallback(() => {
    const influences = headMeshRef.current?.morphTargetInfluences;
    if (!influences) return;
    for (let i = 0; i < influences.length; i++) influences[i] = 0;
  }, []);

  useFakeSpeech(state, setMorph, resetMorphs);

  useFrame((_, delta) => {
    if (!ready) return;
    blinkTimer.current += delta;

    if ((state === "idle" || state === "listening") && blinkTimer.current > 3.2) {
      setMorph("Eyes_Closed_Max", 1);
      if (blinkTimeout.current) clearTimeout(blinkTimeout.current);
      blinkTimeout.current = setTimeout(() => setMorph("Eyes_Closed_Max", 0), 120);
      blinkTimer.current = 0;
    }

    setMorph("Thinking", state === "thinking" ? 0.6 : 0);
    setMorph("Eyebrows_Raised_Left", state === "listening" ? 0.3 : 0);
    setMorph("Eyebrows_Raised_Right", state === "listening" ? 0.3 : 0);

    scene.rotation.y = Math.sin(Date.now() / 4000) * 0.05;
    scene.rotation.x = Math.sin(Date.now() / 5000) * 0.02;
  });

  return <primitive object={scene} scale={6} position={[0, -9.65, 0]} />;
}

useGLTF.preload("/models/vitruvian_head.glb");