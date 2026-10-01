"use client";

import { useEffect, useState } from "react";
import { fetchStatus, fetchVoiceStatus, type VoiceStatus } from "@/lib/api";

export function SystemStatus() {
  const [info, setInfo] = useState("Loading system status...");
  const [voice, setVoice] = useState<VoiceStatus | null>(null);
  const voiceError = voice?.last_error
    ? /No module named ['"]openwakeword['"]/.test(voice.last_error)
      ? "The running backend can't see wake-word support. From backend, start it with: .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload"
      : voice.last_error
    : "";

  useEffect(() => {
    let active = true;
    const poll = () => {
      fetchStatus()
        .then((result) => active && setInfo(result))
        .catch(() => active && setInfo("Unavailable"));
      fetchVoiceStatus()
        .then((result) => active && setVoice(result))
        .catch(() => active && setVoice(null));
    };

    poll();
    const id = setInterval(poll, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <section className="border-t border-[var(--line)] pt-4">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase text-[var(--muted)]">System telemetry</h2>
        <span className="flex items-center gap-2 text-[10px] uppercase text-[#79d4a0]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#79d4a0]" />
          Live
        </span>
      </div>
      <p className="min-h-10 rounded-md border border-[var(--line)] bg-[#0c1214] px-3 py-2.5 font-mono text-xs leading-5 text-[#9eaeaa]">
        {info}
      </p>
      <div className="mt-2 rounded-md border border-[var(--line)] bg-[#0c1214] px-3 py-2.5 text-xs leading-5 text-[#9eaeaa]">
        <div className="flex items-center justify-between">
          <span className="uppercase text-[var(--muted)]">Voice listener</span>
          <span className={voice?.phase === "wake-word listening" ? "text-[#79d4a0]" : "text-[var(--muted)]"}>
            {voice?.phase || "Unavailable"}
          </span>
        </div>
        {voice?.last_heard && <p className="mt-1">Heard: {voice.last_heard}</p>}
        {voiceError && <p className="mt-1 text-[#f08c8c]">{voiceError}</p>}
      </div>
    </section>
  );
}
