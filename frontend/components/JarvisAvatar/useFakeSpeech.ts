import { useEffect, useRef } from "react";
import type { AvatarState } from "./useAvatarState";

export const VISEME_TARGETS = ["aa_02", "ow_08", "p_b_m_21", "f_v_18", "ey_eh_uh_04"];

export function useFakeSpeech(
  state: AvatarState,
  setMorph: (name: string, value: number) => void,
  resetMorphs: () => void
) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (state !== "speaking") {
      if (intervalRef.current) clearInterval(intervalRef.current);
      resetMorphs();
      return;
    }

    intervalRef.current = setInterval(() => {
      resetMorphs();
      const target = VISEME_TARGETS[Math.floor(Math.random() * VISEME_TARGETS.length)];
      const intensity = 0.3 + Math.random() * 0.5;
      setMorph(target, intensity);
    }, 140);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [state, setMorph, resetMorphs]);
}