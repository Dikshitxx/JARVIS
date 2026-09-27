"use client";

import { Suspense } from "react";
import { Canvas } from "@react-three/fiber";
import { AvatarHead } from "./AvatarHead";
import { HudRings } from "./HudRings";
import type { AvatarState } from "./useAvatarState";

export function JarvisAvatar({ state }: { state: AvatarState }) {
  return (
    <div className="h-[340px] w-full overflow-hidden rounded-lg border border-[var(--line)] bg-[#080d0f] sm:h-[420px]">
      <Canvas camera={{ position: [0, 0, 4], fov: 35 }} dpr={[1, 1.5]}>
        <ambientLight intensity={0.7} />
        <directionalLight position={[2, 2, 3]} intensity={1.2} />
        <Suspense fallback={null}>
          <AvatarHead state={state} />
          <HudRings state={state} />
        </Suspense>
      </Canvas>
    </div>
  );
}