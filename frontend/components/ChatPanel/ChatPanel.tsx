"use client";

import { FormEvent, useRef, useState } from "react";
import { resetChat, sendChat } from "@/lib/api";
import type { AvatarState } from "@/components/JarvisAvatar/useAvatarState";

export function ChatPanel({
  onStateChange,
}: {
  onStateChange: (state: AvatarState) => void;
}) {
  const [input, setInput] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const speakingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || busy) return;

    if (speakingTimer.current) clearTimeout(speakingTimer.current);
    setBusy(true);
    onStateChange("thinking");
    try {
      const result = await sendChat(message);
      setReply(result);
      onStateChange("speaking");
      speakingTimer.current = setTimeout(
        () => onStateChange("idle"),
        Math.max(1500, result.length * 45)
      );
    } catch {
      setReply("Error reaching JARVIS backend.");
      onStateChange("idle");
    } finally {
      setBusy(false);
      setInput("");
    }
  };

  const handleReset = async () => {
    if (busy) return;
    if (speakingTimer.current) clearTimeout(speakingTimer.current);
    setBusy(true);
    try {
      await resetChat();
      setReply("");
      onStateChange("idle");
    } catch {
      setReply("Could not reset the conversation.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex min-h-[270px] flex-col border-t border-[var(--line)] pt-5">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase text-[var(--muted)]">Conversation</p>
          <h2 className="mt-1 text-lg font-semibold">Talk to JARVIS</h2>
        </div>
        <button
          type="button"
          onClick={handleReset}
          disabled={busy}
          className="rounded border border-[var(--line)] px-3 py-1.5 text-xs text-[var(--muted)] transition hover:border-[var(--cyan)] hover:text-[var(--cyan)] disabled:opacity-40"
        >
          Reset
        </button>
      </div>

      <div
        aria-live="polite"
        className="mb-4 min-h-[104px] flex-1 whitespace-pre-wrap rounded-md border border-[var(--line)] bg-[#0c1214] p-4 text-sm leading-6 text-[#c7d8d4]"
      >
        {reply || <span className="text-[var(--muted)]">Your conversation will appear here.</span>}
      </div>

      <form onSubmit={handleSend} className="flex gap-2">
        <input
          aria-label="Message for JARVIS"
          className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[#0c1214] px-3 py-3 text-sm text-[var(--foreground)] outline-none transition placeholder:text-[#647674] focus:border-[var(--cyan)]"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onFocus={() => onStateChange("listening")}
          onBlur={() => !busy && onStateChange("idle")}
          placeholder="Write a message..."
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-md bg-[var(--cyan)] px-4 text-sm font-semibold text-[#07100f] transition hover:bg-[#8bf1e2] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Working" : "Send"}
        </button>
      </form>
    </section>
  );
}