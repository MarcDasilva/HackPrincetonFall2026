/** Manifest v2. The schema is frozen in backend/hornsim/manifest.py (SCHEMA) — change BOTH or real runs stop rendering. Every section is optional: an absent section means that stage has not run yet. */
export type Triplet = { healthy?: string; unaided?: string; aided?: string };
export type Score = { unaided?: number; healthy?: number; pick?: number };

export type Scene = {
  id: number; condition: string; clip: string; level_db: number; talker_deg: number;
  noise: { type: string; deg: number | null; snr_db: number | null } | null;
  canal: number; weight: number; deficit_db?: number[]; sii?: Score; haspi?: Score; harm?: boolean;
  neurograms?: Triplet; audio?: Triplet;
};

export type Design = {
  id: number | string; params: Record<string, unknown>; mesh?: string; point?: [number, number];
  gain_curves?: { freqs_hz: number[]; mean: number[]; canals?: number[][] };
  harm_rate?: number; gap_closed?: number; score?: number;
};

export type Card = {
  triage?: string; target_band_hz?: [number, number];
  net_gain_db?: { peak: number; peak_hz: number; canal_worst: number };
  bore?: { throat_mm2?: number; mouth_mm2?: number; length_mm?: number; turns?: number; flare?: string };
  vent?: { count: number; diameter_mm: number; boom_250hz_db?: number; cost_500hz_db?: number };
  print_tolerance?: { throat_mm: number; gain_db: number };
  personalized?: string[]; standard?: string[];
  harm?: { scenes: number; of: number }; gap_closed?: { mean: number; worst: number };
};

export type Manifest = {
  version: number; fake?: boolean; url: string;
  patient?: { id: string; side: string; scale_source?: string; is_average_ear?: boolean; audiogram_is_example?: boolean };
  ear?: { mesh?: string; audiogram?: [number, number][]; params?: Record<string, number>; canal_band?: { volume_cc: [number, number]; samples: number; diameter_mm?: number } };
  waves?: { viewer?: string; directions?: { az: number; el: number; eardrum_peak_hz: number }[]; open_ear?: { az: number; freqs_hz: number[]; gain_db: number[] } };
  scenes?: Scene[];
  neurogram_axes?: { cf_hz: [number, number]; t_s: [number, number] };
  baseline_timeline?: { scene: number; t_ms: number }[];
  target?: { freqs_hz: number[]; gain_db: number[]; reach_db?: number[]; triage: string };
  designs?: Design[];
  tradeoff?: { cloud: [number, number][]; front: [number, number][] };
  agent?: { round: number; line: string }[];
  pick?: number | string;
  card?: Card;
};

export const FAKE = "/demo/results.fake.json";
export const FAKE_COMPARE = "/demo/results.fake-b.json";

export async function loadManifest(url: string): Promise<Manifest> {
  const abs = new URL(url, location.href).href;
  const res = await fetch(abs);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return { ...(await res.json()), url: abs };
}

/** Manifest paths are relative to the manifest file (results/ is served as one folder); absolute URLs pass through. */
export const asset = (m: Manifest, path?: string) => (path ? new URL(path, m.url).href : undefined);

export const picked = (m: Manifest) => m.designs?.find((d) => String(d.id) === String(m.pick));

/** Spec 05's scene grid. Labels only — levels and angles come from each scene. */
export const CONDITIONS: Record<string, string> = {
  C1: "Soft speech", C2: "Conversation", C3: "Talker on aided side", C4: "Talker on far side",
  C5: "Echoey room", C6: "Restaurant", C7: "Noise on aided side", C8: "Loud speech",
};
