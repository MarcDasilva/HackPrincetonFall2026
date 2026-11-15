// Backend calls for the scene grid (backend/app/sim_api.py), proxied under /api by next.config.ts.
import type { EarGrid } from "./fdtd";

export const AVERAGE_ID = "000000000000";

export type PatientInfo = { id: string; average_ear: boolean; side: "left" | "right"; audiogram_db_hl: Record<string, number>; audiogram_is_example: boolean };
export type GridWithPatient = EarGrid & { patient?: PatientInfo };

export type DesignResult = {
  freqs_hz: number[]; target_db: number[]; reach_db: number[]; share: number[];
  key_bands_hz: number[]; guard_bands_hz: number[];
  triage: "passive-suitable" | "partial" | "powered aid recommended"; why: string;
  design: {
    id: string; params: Record<string, number>; objective: number;
    gain_mean_db: number[]; gain_worst_db: number[]; key_met: string; met?: boolean[];
    geometry: Record<string, number | string | boolean>; files: Record<string, string>;
  };
  /** The four distinct buildable designs, best first; `design` is options[0]. ABSENT from designs made before options existed. */
  options?: (DesignResult["design"] & { reason: string; recommended?: boolean })[];
  attempts: { design_id: string; objective: number; ok: boolean; reasons: string[] }[];
  swept: number; elapsed_s: number; notes: string[];
};
export type DesignStatus = { status: "none" | "queued" | "running" | "done" | "error"; log?: string[]; error?: string | null; result?: DesignResult | null };

export type DesignScene = { id: string; name: string; weight: number; deficit_db: number[]; deficit_weighted: number[]; talker_az_deg?: number; talker_el_deg?: number };

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    // FastAPI's 422 detail is a LIST of {loc, msg}: String() of it reads "[object Object]" to the patient.
    const d = body.detail;
    throw new Error(Array.isArray(d) ? d.map((e: { loc?: unknown[]; msg?: string }) => `${(e.loc ?? []).slice(1).join(".")}: ${e.msg}`).join("; ") : d ? String(d) : `HTTP ${r.status}`);
  }
  return r.json();
}

/** `?ear=` for a two-ear patient (the dashboard's runs); without it the backend serves the worse ear. */
const q = (ear?: string) => (ear ? `?ear=${ear}` : "");
export const fetchGrid = (pid: string, ear?: string) => fetch(`/api/sim/patients/${pid}/grid${q(ear)}`).then((r) => json<GridWithPatient>(r));
export const startDesign = (pid: string, audiogram_db_hl: Record<string, number>, scenes: DesignScene[], ear?: string) =>
  fetch(`/api/sim/patients/${pid}/design${q(ear)}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ audiogram_db_hl, scenes }) })
    .then((r) => json<{ status_url: string }>(r));
export const designStatus = (pid: string, ear?: string) => fetch(`/api/sim/patients/${pid}/design${q(ear)}`).then((r) => json<DesignStatus>(r));
export const designFile = (pid: string, did: string, name: string, ear?: string) => `/api/sim/patients/${pid}/design/files/${did}/${name}${q(ear)}`;

export type WaveCheck = {
  design_id: string; freqs_hz: number[]; dx_mm: number; dist_mm: number; canal_len_mm: number;
  model_1d_db: number[]; wave: { az: number; gain_db: number[] }[]; elapsed_s: number; notes: string[];
};
export type WaveStatus = { status: "none" | "queued" | "running" | "done" | "error"; design_id?: string; log?: string[]; error?: string | null; result?: WaveCheck | null };
export const startWaveCheck = (pid: string, azimuths = [0, 90], dx_mm = 1.0, design_id?: string, ear?: string) =>
  fetch(`/api/sim/patients/${pid}/design/wave_check${q(ear)}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ azimuths, dx_mm, design_id }) })
    .then((r) => json<{ status_url: string }>(r));
export const waveStatus = (pid: string, ear?: string) => fetch(`/api/sim/patients/${pid}/design/wave_check${q(ear)}`).then((r) => json<WaveStatus>(r));
/** The earpiece's insertion gain per band, power-averaged over the check's directions: ONE curve the orb applies to every scene. */
export const waveGain = (w: WaveCheck) => w.wave[0].gain_db.map((_, b) => 10 * Math.log10(w.wave.reduce((t, r) => t + 10 ** (r.gain_db[b] / 10), 0) / w.wave.length));
