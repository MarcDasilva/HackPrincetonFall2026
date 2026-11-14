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
  attempts: { design_id: string; objective: number; ok: boolean; reasons: string[] }[];
  swept: number; elapsed_s: number; notes: string[];
};
export type DesignStatus = { status: "none" | "queued" | "running" | "done" | "error"; log?: string[]; error?: string | null; result?: DesignResult | null };

export type DesignScene = { id: string; name: string; weight: number; deficit_db: number[]; deficit_weighted: number[] };

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ? String(body.detail) : `HTTP ${r.status}`);
  }
  return r.json();
}

export const fetchGrid = (pid: string) => fetch(`/api/sim/patients/${pid}/grid`).then((r) => json<GridWithPatient>(r));
export const startDesign = (pid: string, audiogram_db_hl: Record<string, number>, scenes: DesignScene[]) =>
  fetch(`/api/sim/patients/${pid}/design`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ audiogram_db_hl, scenes }) })
    .then((r) => json<{ status_url: string }>(r));
export const designStatus = (pid: string) => fetch(`/api/sim/patients/${pid}/design`).then((r) => json<DesignStatus>(r));
export const designFile = (pid: string, did: string, name: string) => `/api/sim/patients/${pid}/design/files/${did}/${name}`;

export type WaveCheck = {
  design_id: string; freqs_hz: number[]; dx_mm: number; dist_mm: number; canal_len_mm: number;
  model_1d_db: number[]; wave: { az: number; gain_db: number[] }[]; elapsed_s: number; notes: string[];
};
export type WaveStatus = { status: "none" | "queued" | "running" | "done" | "error"; design_id?: string; log?: string[]; error?: string | null; result?: WaveCheck | null };
export const startWaveCheck = (pid: string, azimuths = [0, 90], dx_mm = 1.0) =>
  fetch(`/api/sim/patients/${pid}/design/wave_check`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ azimuths, dx_mm }) })
    .then((r) => json<{ status_url: string }>(r));
export const waveStatus = (pid: string) => fetch(`/api/sim/patients/${pid}/design/wave_check`).then((r) => json<WaveStatus>(r));
