const API_BASE = "/api/backend";

export type TaskStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "WAITING_CONFIRMATION"
  | "WAITING_FOR_USER_INPUT"
  | "SUCCEEDED"
  | "FAILED"
  | "BLOCKED"
  | "TIMED_OUT"
  | "CANCELLED"
  | "UNVERIFIED";

export type TaskRecord = {
  id: string;
  request: string;
  status: TaskStatus;
  current_step: string;
  result: string;
  error: string;
  response_provider?: string;
  response_model?: string;
  cancellation_requested: boolean;
  timed_out: boolean;
  steps: Array<{
    tool_name: string;
    capability: string;
    arguments: Record<string, string>;
    status: string;
    result: string;
    verification: string;
  }>;
};

export type ChatSubmission = {
  task_id?: string;
  status: TaskStatus;
  reply?: string;
  response_provider?: string;
  response_model?: string;
};

export async function sendChat(
  message: string,
  background = true,
): Promise<ChatSubmission> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message, background }),
  });
  if (!res.ok) {
    throw new Error(`Chat request failed: ${res.status}`);
  }
  const data = await res.json();
  return data as ChatSubmission;
}

export async function fetchTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}`);
  if (!res.ok) throw new Error(`Task status request failed: ${res.status}`);
  return (await res.json()) as TaskRecord;
}

export async function cancelTask(taskId: string): Promise<TaskRecord> {
  const res = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Task cancellation failed: ${res.status}`);
  return (await res.json()) as TaskRecord;
}

export async function resetChat(): Promise<void> {
  const res = await fetch(`${API_BASE}/reset`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`Chat reset failed: ${res.status}`);
  }
}

export async function fetchStatus(): Promise<string> {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) return "Status unavailable";
  const data = await res.json();
  return data.info as string;
}

export type VoiceStatus = {
  enabled: boolean;
  phase: string;
  wake_word: string;
  last_heard: string;
  last_reply: string;
  last_error: string;
};

export async function fetchVoiceStatus(): Promise<VoiceStatus> {
  const res = await fetch(`${API_BASE}/voice/status`);
  if (!res.ok) throw new Error(`Voice status request failed: ${res.status}`);
  return (await res.json()) as VoiceStatus;
}
