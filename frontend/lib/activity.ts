export type ActivityItem = { tool: string; args: string; success: boolean; time: string };

export async function fetchActivity(): Promise<ActivityItem[]> {
  const res = await fetch("/api/backend/activity");
  if (!res.ok) return [];
  const data = await res.json();
  return data.items as ActivityItem[];
}