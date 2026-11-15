/** The lead agent's server (agents/src/horn_study/server.py) — a separate process from the backend. */
export const AGENTS = process.env.NEXT_PUBLIC_AGENTS_URL ?? "http://localhost:8010";

/** none = not launched; error = research could not start; stopped = the study's task died with a server restart. */
export type StudyStatus = "none" | "running" | "completed" | "failed" | "cancelled" | "stopped" | "error";
/** stage "new": the run is still processing (or its ear cards have not cleared), so the lead has not spoken yet. */
export type LeadStage = "new" | "opening" | "begin" | "launched" | "sim_ready" | "sim_count" | "sim_prep" | "sim_running" | "design_ready" | "designing" | "options" | "validating" | "final" | "done";
/** One simulation the lead picked (agents lead.PickedScene): talkers and babble around the aided ear, az 0–180 only. */
/** A scene source. `sound` picks a clip from the backend's sound bank (GET /api/sim/sounds/{name}; absent = the speech
 * clips). `dist_mm` puts the speaker that close to the aided ear's canal opening — a phone or a whisper touching the ear;
 * absent = the grid's usual distance. With `dist_mm`, level_db is the free-field level it makes AT the ear. */
export type LeadSource = { role: "talker" | "babble"; az: number; el: number; level_db: number; sound?: string; dist_mm?: number };
export type LeadScene = { id: string; name: string; sound: string; why: string; weight: number; sources: LeadSource[] };
/** One finished simulation as the dashboard reports it; deficit_db is what scene_design designs from. */
export type SimResult = { id: string; name: string; weight: number; sii_healthy: number; sii_unaided: number; deficit_db: number[]; deficit_weighted: number[] };
/** One of the four designs (backend hornsim.scene_design options). */
export type AidOption = { id: string; reason: string; key_met: string; gain_mean_db: number[]; files: Record<string, string>; recommended?: boolean };
/** The simulation half's fields are ABSENT until their stage has produced them. `ear` is the aided ear the study targeted. */
export type LeadReply = {
  run_id: string; stage: LeadStage; reply: string; awaiting_launch: boolean; launch_requested: boolean; study_id: string | null; status: StudyStatus; updated_at: number;
  ear?: "left" | "right" | null; scenes?: LeadScene[] | null; sims?: { results: SimResult[]; audiogram_db_hl: Record<string, number>; summary: string } | null;
  options?: AidOption[] | null; picked?: string | null; validation?: { summary: string } | null; report?: string | null;
};
/** Stages that move on their own (research finishing, the scene picker): the dashboard polls the lead through them. */
export const MOVING: LeadStage[] = ["launched", "sim_prep"];
/** One line of the study's events.jsonl (agents/src/horn_study/events.py StudyEvent); component is the investigator's key for research events. */
export type StudyEvent = { sequence: number; timestamp: string; type: string; component: string; summary: string; data?: Record<string, unknown>; trace?: { run_id: string; project?: string | null; tracing_enabled?: boolean } | null };

const json = async <T,>(res: Response): Promise<T> => {
  if (!res.ok) throw new Error(`lead HTTP ${res.status}`);
  return res.json();
};

/** One message to the lead for this run; "" opens the conversation, or re-reads it if it exists. The run ID IS the session, saved on the agents server. */
export const talkToLead = (runId: string, message: string) =>
  fetch(`${AGENTS}/lead/${runId}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ message }) }).then(json<LeadReply>);

/** A dashboard step (agents lead.EVENTS): sims_done, options, design_failed, picked, validated. Each is accepted in ONE stage only (409 otherwise). */
export const leadEvent = (runId: string, event: string, data: Record<string, unknown> = {}) =>
  fetch(`${AGENTS}/lead/${runId}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ event, data }) }).then(json<LeadReply>);

/** Opens a session for a run that just started, so the picker lists it before the lead speaks. Idempotent. */
export const createSession = (runId: string) => fetch(`${AGENTS}/sessions/${runId}`, { method: "POST" }).then(json<LeadReply>);

/** One saved session; null when the agents server has none for this run (a run started while it was down). */
export const getLead = (runId: string) =>
  fetch(`${AGENTS}/lead/${runId}`).then((res) => (res.status === 404 ? null : json<LeadReply>(res)));

/** Saved sessions, most recently active first. */
export const listSessions = () => fetch(`${AGENTS}/sessions`).then(json<LeadReply[]>);

export const studyEvents = (runId: string) => fetch(`${AGENTS}/lead/${runId}/events`).then(json<{ status: StudyStatus; events: StudyEvent[] }>);
