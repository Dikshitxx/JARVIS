"use client";

import { useEffect, useState } from "react";
import { fetchStatus } from "@/lib/api";

export function SystemStatus() {
  const [info, setInfo] = useState("Loading system status...");

  useEffect(() => {
    let active = true;
    const poll = () => {
      fetchStatus()
        .then((result) => active && setInfo(result))
        .catch(() => active && setInfo("Unavailable"));
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
    </section>
  );
}