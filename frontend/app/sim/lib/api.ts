// Backend calls for the scene grid (backend/app/sim_api.py), proxied under /api by next.config.ts.
import type { HeadGrid, Side } from "./fdtd";

/** The average ear (AudioEar's mean, not anyone's ear) as a right ear, and mirrored as a left ear. */
export const AVERAGE_IDS: Record<Side, string> = { right: "000000000000", left: "000000000001" };
export const isAverage = (pid: string) => pid === AVERAGE_IDS.right || pid === AVERAGE_IDS.left;

export type PatientInfo = { id: string; average_ear: boolean; side: Side; audiogram_db_hl: Record<string, number>; audiogram_is_example: boolean };
export type HeadWithPatients = HeadGrid & { patients?: Record<Side, PatientInfo> };

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

/** Both ears on the dummy head; each id must be a patient scanned for that side. `shape`: the head shape
 * fitted from a front photo (createHeadShape); null = the average head. */
export const fetchHead = (ids: Record<Side, string>, shape: string | null) =>
  fetch(`/api/sim/head?left=${ids.left}&right=${ids.right}${shape ? `&shape=${shape}` : ""}`).then((r) => json<HeadWithPatients>(r));

export type HeadShapeMeta = {
  measured: boolean; breadth_mm: number; bizygomatic_mm: number; length_mm: number; chin_mm: number; crown_mm: number;
  eye_line_mm: number; ipd_mm: number; mm_per_px: number; roll_deg: number; yaw_deg: number | null;
};
export type HeadShapeFit = {
  id: string; meta: HeadShapeMeta; warnings: string[];
  overlay: { silhouette_px: number[][]; face_oval_px: number[][]; canal_line_px: number[][]; measured_to_px: number };
};
/** Fit the head from a front photo's face landmarks (the photo itself stays in the browser). */
export const createHeadShape = (face: { landmarks: number[][]; image_w: number; image_h: number; yaw_deg: number | null }) =>
  fetch("/api/sim/head_shapes", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(face) })
    .then((r) => json<HeadShapeFit>(r));
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
