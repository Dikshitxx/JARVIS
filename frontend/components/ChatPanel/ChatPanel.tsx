"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { cancelTask, fetchTask, resetChat, sendChat, type TaskStatus } from "@/lib/api";
import type { AvatarState } from "@/components/JarvisAvatar/useAvatarState";

type ChatItem = {
  id: string;
  taskId?: string;
  request: string;
  status: TaskStatus | "SUBMITTING";
  reply: string;
  currentStep: string;
  cancellationRequested?: boolean;
};

const ACTIVE_STATUSES = new Set<TaskStatus | "SUBMITTING">([
  "SUBMITTING", "PENDING", "RUNNING", "WAITING_CONFIRMATION", "WAITING_FOR_USER_INPUT",
]);

function deriveCurrentStep(status: TaskStatus | "SUBMITTING", reply: string): string {
  switch (status) {
    case "SUBMITTING":
      return "Submitting request";
    case "PENDING":
      return "Queued";
    case "RUNNING":
      return "Working";
    case "WAITING_CONFIRMATION":
    case "WAITING_FOR_USER_INPUT":
      return "Waiting for confirmation";
    case "SUCCEEDED":
      return reply ? "Complete" : "Completed";
    case "FAILED":
      return "Failed";
    case "BLOCKED":
      return "Blocked";
    case "TIMED_OUT":
      return "Timed out";
    case "CANCELLED":
      return "Cancelled";
    case "UNVERIFIED":
      return "Unverified";
    default:
      return reply ? "Complete" : "Queued";
  }
}

export function ChatPanel({
  onStateChange,
}: {
  onStateChange: (state: AvatarState) => void;
}) {
  const [input, setInput] = useState("");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const speakingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generation = useRef(0);
  const spoken = useRef(new Set<string>());

  useEffect(() => {
    const active = items.filter((item) => item.taskId && ACTIVE_STATUSES.has(item.status));
    if (!active.length) return;
    const currentGeneration = generation.current;

    const poll = async () => {
      const updates = await Promise.all(active.map(async (item) => {
        try {
          return { id: item.id, task: await fetchTask(item.taskId!) };
        } catch {
          return null;
        }
      }));
      if (generation.current !== currentGeneration) return;
      setItems((current) => {
        let changed = false;
        const next = current.map((item) => {
          const update = updates.find((candidate) => candidate?.id === item.id);
          if (!update) return item;
          const task = update.task;
          const values = {
            ...item,
            status: task.status,
            currentStep: task.status === "WAITING_FOR_USER_INPUT" || task.status === "WAITING_CONFIRMATION"
              ? "Waiting for confirmation"
              : task.current_step || deriveCurrentStep(task.status, task.result || item.reply),
            reply: task.result || item.reply,
            cancellationRequested: task.cancellation_requested,
          };
          if (values.status !== item.status || values.currentStep !== item.currentStep ||
              values.reply !== item.reply || values.cancellationRequested !== item.cancellationRequested) changed = true;
          return values;
        });
        return changed ? next : current;
      });
    };

    void poll();
    const timer = setInterval(() => void poll(), 800);
    return () => clearInterval(timer);
  }, [items]);

  useEffect(() => {
    for (const item of items) {
      if (!item.reply || ACTIVE_STATUSES.has(item.status) || spoken.current.has(item.id)) continue;
      spoken.current.add(item.id);
      if (speakingTimer.current) clearTimeout(speakingTimer.current);
      onStateChange("speaking");
      speakingTimer.current = setTimeout(() => onStateChange("idle"), Math.max(1500, item.reply.length * 35));
      break;
    }
  }, [items, onStateChange]);

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || submitting) return;

    const localId = `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setItems((current) => [...current, {
      id: localId, request: message, status: "SUBMITTING" as const, reply: "", currentStep: "Submitting request",
    }].slice(-12));
    setSubmitting(true);
    setInput("");
    onStateChange("thinking");
    try {
      const result = await sendChat(message);
      setItems((current) => current.map((item) => item.id !== localId ? item : {
        ...item,
        taskId: result.task_id,
        status: result.status,
        reply: result.reply || "",
        currentStep: deriveCurrentStep(result.status ?? "PENDING", result.reply || ""),
      }));
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Error reaching JARVIS backend.";
      setItems((current) => current.map((item) => item.id !== localId ? item : {
        ...item, status: "FAILED" as const, reply: detail, currentStep: "Failed to submit",
      }));
      onStateChange("idle");
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = async (item: ChatItem) => {
    if (!item.taskId) return;
    try {
      const task = await cancelTask(item.taskId);
      setItems((current) => current.map((entry) => entry.id !== item.id ? entry : {
        ...entry,
        status: task.status,
        currentStep: task.current_step,
        reply: task.result || entry.reply,
        cancellationRequested: task.cancellation_requested,
      }));
    } catch {
      setItems((current) => current.map((entry) => entry.id !== item.id ? entry : {
        ...entry, reply: "JARVIS could not confirm the cancellation request.",
      }));
    }
  };

  const handleReset = async () => {
    if (submitting) return;
    if (speakingTimer.current) clearTimeout(speakingTimer.current);
    generation.current += 1;
    setSubmitting(true);
    try {
      await resetChat();
      setItems([]);
      spoken.current.clear();
      onStateChange("idle");
    } catch {
      setItems((current) => [...current, {
        id: `reset-${Date.now()}`, request: "Reset", status: "FAILED" as const,
        reply: "Could not reset the conversation.", currentStep: "Reset failed",
      }]);
    } finally {
      setSubmitting(false);
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
          disabled={submitting}
          className="rounded border border-[var(--line)] px-3 py-1.5 text-xs text-[var(--muted)] transition hover:border-[var(--cyan)] hover:text-[var(--cyan)] disabled:opacity-40"
        >
          Reset
        </button>
      </div>

      <div
        aria-live="polite"
        className="mb-4 min-h-[104px] max-h-[300px] flex-1 space-y-3 overflow-y-auto rounded-md border border-[var(--line)] bg-[#0c1214] p-4 text-sm leading-6 text-[#c7d8d4]"
      >
        {items.length ? items.map((item) => (
          <article key={item.id} className="border-b border-[var(--line)] pb-3 last:border-0 last:pb-0">
            <p className="text-[var(--foreground)]">{item.request}</p>
            <p className="mt-1 text-xs uppercase tracking-wide text-[var(--muted)]">
              {item.status.replaceAll("_", " ")}{item.currentStep ? ` · ${item.currentStep}` : ""}
              {item.cancellationRequested ? " · stopping after current operation" : ""}
            </p>
            {item.reply && <p className="mt-1 whitespace-pre-wrap">{item.reply}</p>}
            {item.taskId && ACTIVE_STATUSES.has(item.status) && (
              <button
                type="button"
                onClick={() => void handleCancel(item)}
                disabled={item.cancellationRequested}
                className="mt-2 rounded border border-[var(--line)] px-2 py-1 text-xs text-[var(--muted)] hover:border-[#ff746f] hover:text-[#ff746f] disabled:opacity-40"
              >
                {item.cancellationRequested ? "Stopping" : "Cancel"}
              </button>
            )}
          </article>
        )) : <span className="text-[var(--muted)]">Your conversation will appear here.</span>}
      </div>

      <form onSubmit={handleSend} className="flex gap-2">
        <input
          aria-label="Message for JARVIS"
          className="min-w-0 flex-1 rounded-md border border-[var(--line)] bg-[#0c1214] px-3 py-3 text-sm text-[var(--foreground)] outline-none transition placeholder:text-[#647674] focus:border-[var(--cyan)]"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onFocus={() => onStateChange("listening")}
          onBlur={() => !submitting && onStateChange("idle")}
          placeholder="Write a message..."
        />
        <button
          type="submit"
          disabled={submitting || !input.trim()}
          className="rounded-md bg-[var(--cyan)] px-4 text-sm font-semibold text-[#07100f] transition hover:bg-[#8bf1e2] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? "Sending" : "Send"}
        </button>
      </form>
    </section>
  );
}
