// Scene presets from backend/hornsim/scenes.py (spec 05), placed around the dummy head.
// Azimuth (head frame): 0 front, 90 the right ear's side, 180 behind, 270 the left ear's side.
// Both ears hear every scene, so "aided side / far side" is now just where the talker stands.

/** talker: speech. babble: other voices. music: a club PA, a concert. traffic: road noise. alarm: a smoke
 * alarm or siren. birds: birdsong. target: the sound the listener wants to hear (default: talkers);
 * everything else masks it. custom: optional audio of your own for listening (stays in the browser). */
import { SOUNDS, type Role } from "./sounds";
export type { Role };
export type Source = { id: string; role: Role; az: number; el: number; levelDb: number; target?: boolean; custom?: { name: string; url: string } };
export type Scene = { id: string; name: string; condition?: string; why?: string; weight: number; sources: Source[] };

let n = 0;
const uid = (p: string) => `${p}${++n}`;
const talker = (az: number, levelDb: number, el = 0): Source => ({ id: uid("t"), role: "talker", az, el, levelDb });
const babble = (az: number, levelDb: number, el = 0): Source => ({ id: uid("b"), role: "babble", az, el, levelDb });
const music = (az: number, levelDb: number, el = 0): Source => ({ id: uid("m"), role: "music", az, el, levelDb });
const traffic = (az: number, levelDb: number, el = 0): Source => ({ id: uid("r"), role: "traffic", az, el, levelDb });
const alarm = (az: number, levelDb: number, el = 0): Source => ({ id: uid("a"), role: "alarm", az, el, levelDb, target: true });
const birds = (az: number, levelDb: number, el = 0): Source => ({ id: uid("w"), role: "birds", az, el, levelDb, target: true });
const wanted = (s: Source): Source => ({ ...s, target: true });

export const PRESETS: { condition: string; name: string; make?: () => Source[]; why?: string }[] = [
  { condition: "C1", name: "Soft speech", make: () => [talker(0, 50)] },
  { condition: "C2", name: "Conversation", make: () => [talker(0, 65)] },
  { condition: "C3", name: "Talker on the right", make: () => [talker(90, 65)] },
  { condition: "C4", name: "Talker on the left", make: () => [talker(270, 65)] },
  { condition: "C5", name: "Echoey room", why: "reverb is not in the live grid yet" },
  { condition: "C6", name: "Restaurant", make: () => [talker(0, 65), babble(0, 60)] },
  { condition: "C7", name: "Noise on the right", make: () => [talker(0, 65), babble(90, 60)] },
  { condition: "C8", name: "Loud speech", make: () => [talker(0, 80)] },
  // everyday scenes beyond the spec's set (levels: typical published ranges, rounded)
  { condition: "S1", name: "Rave / club", make: () => [wanted(music(0, 100, 10))] },   // the music is what you came for
  { condition: "S2", name: "Concert", make: () => [wanted(music(0, 95, 15)), babble(180, 72)] },
  { condition: "S3", name: "Café", make: () => [talker(0, 63), babble(100, 60), babble(250, 60)] },
  { condition: "S4", name: "Car, passenger talking", make: () => [traffic(150, 70, -20), traffic(210, 70, -20), talker(270, 66)] },
  { condition: "S5", name: "Busy street", make: () => [traffic(270, 76), talker(30, 70)] },
  { condition: "S6", name: "Classroom", make: () => [talker(0, 58, 5), babble(120, 52)] },
  // sounds that are not speech but matter: safety and the world around you
  { condition: "S7", name: "Smoke alarm, TV on", make: () => [alarm(150, 65, 20), babble(0, 62)] },
  { condition: "S8", name: "Siren while driving", make: () => [alarm(180, 68), traffic(150, 70, -20), traffic(210, 70, -20)] },
  { condition: "S9", name: "Birdsong in the park", make: () => [birds(60, 50, 30), traffic(270, 58)] },
  { condition: "S10", name: "Music at home", make: () => [wanted(music(330, 70)), wanted(music(30, 70))] },
];

export function sceneFromPreset(condition: string): Scene {
  const p = PRESETS.find((q) => q.condition === condition && q.make)!;
  return { id: uid("s"), name: p.name, condition: p.condition, weight: 1, sources: p.make!() };
}

const EXTRA: (() => Scene)[] = [
  () => ({ id: uid("s"), name: "Talker above, front", weight: 1, sources: [talker(30, 65, 35)] }),
  () => ({ id: uid("s"), name: "Talker behind", weight: 1, sources: [talker(180, 65)] }),
  () => ({ id: uid("s"), name: "Noise behind", weight: 1, sources: [talker(0, 65), babble(180, 62)] }),
  () => ({ id: uid("s"), name: "Two talkers", weight: 1, sources: [talker(330, 62), talker(60, 62)] }),
];

/** n×n starting scenes: the live presets first, then variations. */
export function defaultScenes(count: number): Scene[] {
  const live = PRESETS.filter((p) => p.make).map((p) => () => sceneFromPreset(p.condition));
  const makers = [...live, ...EXTRA];
  return Array.from({ length: count }, (_, i) =>
    i < makers.length ? makers[i]() : { id: uid("s"), name: `Custom ${i + 1}`, weight: 1, sources: [talker((i * 67) % 360, 65, ((i * 23) % 60) - 20)] });
}

export const newSource = (role: Role): Source => {
  const d = SOUNDS[role];
  return { id: uid(role[0]), role, az: d.az, el: d.el, levelDb: d.level, target: d.target };
};

/** A scene set from the research step (backend hornsim/scene_spec.py, GET /api/sim/scene_sets/{id}). */
export type SceneSet = { id?: string; source: string; scenes: { name: string; why: string; weight: number; tags: string[];
  sources: { role: Role; az: number; el: number; level_db: number; target: boolean }[] }[] };
export function scenesFromSet(set: SceneSet): Scene[] {
  return set.scenes.map((s) => ({ id: uid("s"), name: s.name, why: s.why, weight: s.weight,
    sources: s.sources.map((x) => ({ id: uid(x.role[0]), role: x.role, az: x.az, el: x.el, levelDb: x.level_db, target: x.target })) }));
}

/** Sources share runs: one key per direction, rounded to the grid's useful resolution. */
export const dirKey = (az: number, el: number) => `${((Math.round(az) % 360) + 360) % 360},${Math.round(el)}`;
