/** The lead agent's server (agents/src/horn_study/server.py) — a separate process from the backend. */
export const AGENTS = process.env.NEXT_PUBLIC_AGENTS_URL ?? "http://localhost:8010";

export type LeadReply = { reply: string; awaiting_launch: boolean; launch_requested: boolean };

/** One message to the lead for this run; "" opens the conversation. The run ID IS the conversation, held in the server's memory. */
export async function talkToLead(runId: string, message: string): Promise<LeadReply> {
  const res = await fetch(`${AGENTS}/lead/${runId}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ message }) });
  if (!res.ok) throw new Error(`lead HTTP ${res.status}`);
  return res.json();
}
