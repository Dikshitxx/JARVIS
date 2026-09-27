import { useCallback, useState } from "react";

export type AvatarState = "idle" | "listening" | "thinking" | "speaking";

export function useAvatarState() {
  const [state, setState] = useState<AvatarState>("idle");
  const toIdle = useCallback(() => setState("idle"), []);
  const toListening = useCallback(() => setState("listening"), []);
  const toThinking = useCallback(() => setState("thinking"), []);
  const toSpeaking = useCallback(() => setState("speaking"), []);
  return { state, toIdle, toListening, toThinking, toSpeaking };
}