"use client";

import { useEffect, useState } from "react";
import { fetchActivity, type ActivityItem } from "@/lib/activity";

export function ActivityFeed() {
  const [items, setItems] = useState<ActivityItem[]>([]);

  useEffect(() => {
    const poll = () => fetchActivity().then(setItems).catch(() => {});
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-3 bg-zinc-950 rounded-xl border border-zinc-800 text-xs font-mono max-h-40 overflow-y-auto">
      <div className="text-zinc-500 mb-1">CURRENT ACTIVITY</div>
      {items.length === 0 && <div className="text-zinc-600">Idle.</div>}
      {items.map((it, i) => (
        <div key={i} className={it.success ? "text-cyan-300" : "text-red-400"}>
          › {it.tool} {it.args}
        </div>
      ))}
    </div>
  );
}