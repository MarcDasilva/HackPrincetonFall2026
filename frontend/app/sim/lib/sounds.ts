// The sound types the scene grid can simulate, in one place. Mirrors backend/hornsim/scene_spec.py
// SOUNDS (the vocabulary the research step builds scene sets from); test_scene_spec.py checks both
// lists hold the same roles. To add a sound: an entry here and there, its spectrum shape in
// hearing.ts (sourceBands) and its sound in binaural.ts (clipFor) / soundGen.ts.
export const SOUNDS = {
  talker: { label: "talker", menu: "talker (speech to follow)", color: "#d95926", speech: true, target: true, level: 65, el: 0, az: 45 },
  babble: { label: "babble", menu: "babble (other voices)", color: "#3987e5", speech: true, target: false, level: 60, el: 0, az: 225 },
  music: { label: "music", menu: "music (club, concert)", color: "#c98500", speech: false, target: false, level: 85, el: 10, az: 0 },
  traffic: { label: "traffic", menu: "traffic (road noise)", color: "#199e70", speech: false, target: false, level: 72, el: -10, az: 270 },
  alarm: { label: "alarm", menu: "alarm (smoke alarm, siren)", color: "#e66767", speech: false, target: true, level: 70, el: 20, az: 150 },
  birds: { label: "birds", menu: "birds (birdsong)", color: "#9b7be0", speech: false, target: true, level: 52, el: 30, az: 60 },
} as const;
export type Role = keyof typeof SOUNDS;
export const ROLES = Object.keys(SOUNDS) as Role[];
