// Scene presets from backend/hornsim/scenes.py (spec 05). Azimuth: 0 front, 90 aided side, 180 behind.
// The browser grid holds speakers on the aided half (0–180°): the flat head plane cannot pass sound
// to the far side, which the backend models with a spherical head instead.

export type Source = { id: string; role: "talker" | "babble"; az: number; el: number; levelDb: number };
export type Scene = { id: string; name: string; condition?: string; weight: number; sources: Source[] };

let n = 0;
const uid = (p: string) => `${p}${++n}`;
const talker = (az: number, levelDb: number, el = 0): Source => ({ id: uid("t"), role: "talker", az, el, levelDb });
const babble = (az: number, levelDb: number, el = 0): Source => ({ id: uid("b"), role: "babble", az, el, levelDb });

export const PRESETS: { condition: string; name: string; make?: () => Source[]; why?: string }[] = [
  { condition: "C1", name: "Soft speech", make: () => [talker(0, 50)] },
  { condition: "C2", name: "Conversation", make: () => [talker(0, 65)] },
  { condition: "C3", name: "Talker on aided side", make: () => [talker(90, 65)] },
  { condition: "C4", name: "Talker on far side", why: "far side needs the spherical-head model (backend only)" },
  { condition: "C5", name: "Echoey room", why: "reverb is not in the live grid yet" },
  { condition: "C6", name: "Restaurant", make: () => [talker(0, 65), babble(0, 60)] },
  { condition: "C7", name: "Noise on aided side", make: () => [talker(0, 65), babble(90, 60)] },
  { condition: "C8", name: "Loud speech", make: () => [talker(0, 80)] },
];

export function sceneFromPreset(condition: string): Scene {
  const p = PRESETS.find((q) => q.condition === condition && q.make)!;
  return { id: uid("s"), name: p.name, condition: p.condition, weight: 1, sources: p.make!() };
}

const EXTRA: (() => Scene)[] = [
  () => ({ id: uid("s"), name: "Talker above, front", weight: 1, sources: [talker(30, 65, 35)] }),
  () => ({ id: uid("s"), name: "Talker behind", weight: 1, sources: [talker(150, 65)] }),
  () => ({ id: uid("s"), name: "Noise behind", weight: 1, sources: [talker(0, 65), babble(165, 62)] }),
  () => ({ id: uid("s"), name: "Two talkers", weight: 1, sources: [talker(20, 62), talker(110, 62)] }),
];

/** n×n starting scenes: the live presets first, then variations. */
export function defaultScenes(count: number): Scene[] {
  const live = PRESETS.filter((p) => p.make).map((p) => () => sceneFromPreset(p.condition));
  const makers = [...live, ...EXTRA];
  return Array.from({ length: count }, (_, i) =>
    i < makers.length ? makers[i]() : { id: uid("s"), name: `Custom ${i + 1}`, weight: 1, sources: [talker((i * 37) % 180, 65, ((i * 23) % 60) - 20)] });
}

export const newSource = (role: Source["role"]): Source => (role === "talker" ? talker(45, 65) : babble(135, 60));

/** Sources share runs: one key per direction, rounded to the grid's useful resolution. */
export const dirKey = (az: number, el: number) => `${Math.round(az)},${Math.round(el)}`;
