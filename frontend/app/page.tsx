"use client";

import { ChatPanel } from "@/components/ChatPanel/ChatPanel";
import { ActivityFeed } from "@/components/ActivityFeed";
import { JarvisAvatar } from "@/components/JarvisAvatar/JarvisAvatar";
import { useAvatarState, type AvatarState } from "@/components/JarvisAvatar/useAvatarState";
import { SystemStatus } from "@/components/SystemStatus";

export default function Home() {
  const { state, toIdle, toListening, toThinking, toSpeaking } = useAvatarState();

  const handleStateChange = (nextState: AvatarState) => {
    const transitions: Record<AvatarState, () => void> = {
      idle: toIdle,
      listening: toListening,
      thinking: toThinking,
      speaking: toSpeaking,
    };
    transitions[nextState]();
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-[1440px] flex-col px-4 pb-8 sm:px-7 lg:px-10">
      <header className="flex min-h-[76px] items-center justify-between border-b border-[var(--line)]">
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-md border border-[var(--cyan)]/40 text-sm font-bold text-[var(--cyan)]">
            J
          </div>
          <div>
            <h1 className="text-sm font-semibold">JARVIS</h1>
            <p className="text-[10px] uppercase text-[var(--muted)]">Personal system interface</p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase text-[#9eaeaa] sm:text-xs">
          <span className="h-1.5 w-1.5 rounded-full bg-[#79d4a0] shadow-[0_0_10px_#79d4a0]" />
          <span>System online</span>
          <span className="hidden text-[var(--muted)] sm:inline">/</span>
          <span className="hidden text-[var(--cyan)] sm:inline">{state}</span>
        </div>
      </header>

      <div className="grid flex-1 gap-8 py-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.85fr)] lg:gap-10 lg:py-9">
        <section className="flex min-w-0 flex-col">
          <div className="mb-4 flex items-end justify-between">
            <div>
              <p className="mb-1 text-[10px] uppercase text-[var(--muted)]">Visual interface</p>
              <h2 className="text-xl font-semibold">Presence</h2>
            </div>
            <span className="font-mono text-[10px] text-[var(--muted)]">AVATAR / 01</span>
          </div>
          <JarvisAvatar state={state} />
          <div className="mt-3 flex items-center justify-between text-[10px] uppercase text-[var(--muted)]">
            <span>Expression engine · Stage A</span>
            <span>{state}</span>
          </div>
        </section>

        <aside className="flex min-w-0 flex-col gap-7 lg:pt-1">
          <ChatPanel onStateChange={handleStateChange} />
          <SystemStatus />
          <ActivityFeed />
        </aside>
      </div>
    </main>
  );
}