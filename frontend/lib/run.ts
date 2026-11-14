import { MAX_HL, type Ear, type Result } from "@/lib/audiometry";

/** Horn-aid backend (backend/app/main.py). CORS is open by default there; set this when it is hosted elsewhere. */
export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** files maps a generated file's name to its URL path (relative to API); entries appear as each stage writes them. */
export type Run = { id: string; status: string; step?: string | null; error?: string | null; files?: Record<string, string>; example?: boolean };

/** Both ears' thresholds, in dB HL: the backend picks the one for the ear it finds in the photo, which the app does not know until the backend says. "nr" has no number, so it becomes one step past the loudest tone played (MAX_HL) — "worse than anything we could test", not a guess at the real level. */
export const audiogramOf = (r: Result) =>
  JSON.stringify(Object.fromEntries((["right", "left"] as const).map((ear) => [ear, Object.fromEntries(Object.entries(r.thresholds[ear]).map(([f, v]) => [f, v === "nr" ? MAX_HL + 10 : v]))])));

/**
 * Starts a run. `result` is the in-app hearing test; an UPLOADED report has none (no PDF or image reader exists), so the audiogram goes blank and the backend substitutes its example — runNote says so, or a stranger's audiogram would silently design this ear's aid.
 * `box` (x0,y0,x1,y1 in photo pixels) and `side` are OMITTED unless the caller knows them: the backend then finds the ear itself by sending the photo to Claude (backend/earrecon/detect.py). Sending both skips that call. A guessed box is worse than none — it is SAM 2's prompt, and one that clips the ear or swallows the face ruins the fit.
 */
export async function startRun(photo: Blob, result?: Result, box?: [number, number, number, number], side?: Ear): Promise<Run> {
  const fd = new FormData();
  fd.set("photo", photo, "ear.jpg");
  if (box) fd.set("box", box.join(","));
  if (side) fd.set("side", side);
  fd.set("audiogram", result ? audiogramOf(result) : "");
  const res = await fetch(`${API}/api/patients`, { method: "POST", body: fd });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : `The server refused the run (HTTP ${res.status})`);
  }
  return { id: (await res.json()).id, status: "queued", example: !result };
}

export async function pollRun(run: Run): Promise<Run> {
  const j = await (await fetch(`${API}/api/patients/${run.id}`)).json();
  return { ...run, status: j.status, step: j.step, error: j.error, files: j.files };
}

/** Text for the chat box's status line, or "" for none. Progress (queued, running) is NOT here: the orb's "Processing…" label already tracks it, and a second label would disagree about when the run starts and ends. Only what the orb cannot say: a failure, and the example-audiogram caveat. */
export const runNote = (r: Run) =>
  r.status === "error" ? (r.error ?? "The run failed.") : r.example ? "Using the example audiogram; uploaded reports are not read yet." : "";
