"""Scene sets for the scene grid (/sim): the shared vocabulary, validation, and a first suggestion from a
user's needs. This is how the research step (agents/) asks for the simulations a user needs:

    1. GET  /api/sim/scene_vocabulary   what can be simulated: SOUNDS (roles), ranges, the scene format
    2. build a scene set from the user's needs (suggest_scenes is a deterministic start; the research
       step can replace or extend it, citing why each scene matters for this user)
    3. POST /api/sim/scene_sets          validated and stored -> id
    4. /sim?left=..&right=..&head=..&scenes=<id>   the grid opens on those scenes

A scene: {name, why, weight, tags, sources: [{role, az, el, level_db, target}]}. az: 0 front, 90 right
ear side, 180 behind, 270 left; el up. level_db: dB SPL at the head. target: the sound this scene is
about (speech, music, an alarm...); everything else masks it. Speech targets are scored with the SII,
any other target with an audibility index weighted by where that sound carries its energy (frontend
app/sim/lib/hearing.ts). Roles must exist in SOUNDS; the frontend registry (app/sim/lib/sounds.ts)
renders and scores each one, and test_scene_spec.py keeps the two lists equal.

    python -m hornsim.scene_spec '{"activities": ["concerts", "driving"]}'     # print a suggestion
"""
import json
import re
import sys

# role -> what it is, whether it is speech, the default for `target`, a typical level range (dB SPL at
# the head), default elevation, and the needs words that call for it
SOUNDS = {
    "talker": {"label": "speech", "speech": True, "target": True, "level_db": (45, 85), "el": 0,
               "description": "one person talking: the speech to follow"},
    "babble": {"label": "other voices", "speech": True, "target": False, "level_db": (45, 80), "el": 0,
               "description": "several people talking at once (restaurant, party, classroom chatter)"},
    "music": {"label": "music", "speech": False, "target": False, "level_db": (50, 110), "el": 10,
              "description": "music from speakers or a stage; club and concert levels reach 95-105 dB"},
    "traffic": {"label": "traffic", "speech": False, "target": False, "level_db": (50, 85), "el": -10,
                "description": "road noise: engines and tyres, mostly low frequencies"},
    "alarm": {"label": "alarm", "speech": False, "target": True, "level_db": (55, 90), "el": 20,
              "description": "a smoke alarm, siren or alert tone (~3 kHz): a safety cue"},
    "birds": {"label": "birdsong", "speech": False, "target": True, "level_db": (35, 70), "el": 30,
              "description": "birdsong and other high, quiet environmental sounds (2.5-8 kHz)"},
}
LIMITS = {"scenes": 16, "sources": 6, "az": (0, 360), "el": (-30, 60), "level_db": (30, 110), "weight": (0, 10)}

# Building blocks for suggest_scenes: a library of scenes, each tagged; NEEDS maps words in a user's
# activities/goals/priorities to tags. Deterministic on purpose: the research step refines it.
LIBRARY = [
    {"name": "Conversation", "tags": ["speech", "quiet"], "why": "everyday one-to-one talk",
     "sources": [{"role": "talker", "az": 0, "level_db": 65}]},
    {"name": "Soft speech", "tags": ["speech", "quiet"], "why": "quiet talkers, the hardest speech to catch",
     "sources": [{"role": "talker", "az": 0, "level_db": 50}]},
    {"name": "Restaurant", "tags": ["speech", "noise", "social"], "why": "talk over other voices",
     "sources": [{"role": "talker", "az": 0, "level_db": 65}, {"role": "babble", "az": 120, "level_db": 62},
                 {"role": "babble", "az": 240, "level_db": 62}]},
    {"name": "Meeting, talker to the side", "tags": ["speech", "work"], "why": "group talk from the sides",
     "sources": [{"role": "talker", "az": 60, "level_db": 63}, {"role": "talker", "az": 300, "level_db": 63}]},
    {"name": "Classroom", "tags": ["speech", "school", "distance"], "why": "a talker at a distance with chatter",
     "sources": [{"role": "talker", "az": 0, "el": 5, "level_db": 58}, {"role": "babble", "az": 120, "level_db": 52}]},
    {"name": "Kids at home", "tags": ["speech", "family", "high-pitch"], "why": "children's voices from around the room",
     "sources": [{"role": "talker", "az": 200, "level_db": 60}, {"role": "music", "az": 30, "level_db": 58}]},
    {"name": "Car, passenger talking", "tags": ["speech", "driving", "noise"], "why": "talk over road noise",
     "sources": [{"role": "talker", "az": 270, "level_db": 66}, {"role": "traffic", "az": 150, "el": -20, "level_db": 70},
                 {"role": "traffic", "az": 210, "el": -20, "level_db": 70}]},
    {"name": "Siren while driving", "tags": ["safety", "driving"], "why": "hearing an emergency vehicle behind",
     "sources": [{"role": "alarm", "az": 180, "level_db": 68}, {"role": "traffic", "az": 150, "el": -20, "level_db": 70},
                 {"role": "traffic", "az": 210, "el": -20, "level_db": 70}]},
    {"name": "Smoke alarm, TV on", "tags": ["safety", "home"], "why": "an alarm from another room",
     "sources": [{"role": "alarm", "az": 150, "el": 20, "level_db": 65}, {"role": "babble", "az": 0, "level_db": 62}]},
    {"name": "Busy street", "tags": ["speech", "outdoors", "noise", "safety"], "why": "talk and traffic awareness outside",
     "sources": [{"role": "talker", "az": 30, "level_db": 70}, {"role": "traffic", "az": 270, "level_db": 76}]},
    {"name": "Birdsong in the park", "tags": ["nature", "outdoors", "high-pitch"], "why": "quiet high sounds of the world around",
     "sources": [{"role": "birds", "az": 60, "el": 30, "level_db": 50}, {"role": "traffic", "az": 270, "level_db": 58}]},
    {"name": "Music at home", "tags": ["music", "home"], "why": "enjoying recorded music",
     "sources": [{"role": "music", "az": 330, "level_db": 70, "target": True}, {"role": "music", "az": 30, "level_db": 70, "target": True}]},
    {"name": "Concert", "tags": ["music", "loud", "social"], "why": "live music (loud: protection matters)",
     "sources": [{"role": "music", "az": 0, "el": 15, "level_db": 95, "target": True}, {"role": "babble", "az": 180, "level_db": 72}]},
    {"name": "Rave / club", "tags": ["music", "loud", "social"], "why": "club music (very loud: protection matters)",
     "sources": [{"role": "music", "az": 0, "el": 10, "level_db": 100, "target": True}]},
]
NEEDS = {  # word in the user's needs -> tags of the scenes it calls for
    r"\b(talk|conversation|chat|friends?|partner|spouse)\b": ["speech"],
    r"\b(restaurant|bar|pub|party|parties|dinner|caf[eé])s?\b": ["social", "noise"],
    r"\b(meeting|work|office|colleague)s?\b": ["work"],
    r"\b(class|school|lecture|teacher|student)s?\b": ["school"],
    r"\b(kid|child|children|grandkid|grandchild|baby|family)s?\b": ["family"],
    r"\b(driv\w*|car|commut\w*)\b": ["driving"],
    r"\b(safe\w*|alarm|siren|alert|doorbell)s?\b": ["safety"],
    r"\b(walk\w*|street|outdoor\w*|city|bik\w*|run\w*|hik\w*)\b": ["outdoors"],
    r"\b(bird\w*|nature|park|garden\w*)\b": ["nature"],
    r"\b(music|song|listen\w*|album|record)s?\b": ["music"],
    r"\b(concert|gig|festival|rave|club|clubbing|dj)s?\b": ["loud", "music"],
    r"\b(tv|television|movie|film)s?\b": ["home"],
    r"\b(quiet|soft|whisper)\w*\b": ["quiet"],
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def validate_scene_set(d):
    """A scene set from anywhere (the research step, a file, the browser) -> normalised dict, or ValueError
    naming the first problem. Unknown roles are refused: the grid could not render or score them."""
    if not isinstance(d, dict) or not isinstance(d.get("scenes"), list) or not d["scenes"]:
        raise ValueError("a scene set is {\"source\": \"...\", \"scenes\": [ ... ]} with at least one scene")
    if len(d["scenes"]) > LIMITS["scenes"]:
        raise ValueError(f"at most {LIMITS['scenes']} scenes (the grid shows up to 4x4)")
    out = []
    for i, s in enumerate(d["scenes"]):
        where = f"scene {i + 1}"
        if not isinstance(s, dict) or not str(s.get("name", "")).strip():
            raise ValueError(f"{where}: needs a name")
        srcs = s.get("sources")
        if not isinstance(srcs, list) or not srcs or len(srcs) > LIMITS["sources"]:
            raise ValueError(f"{where} ({s['name']}): 1 to {LIMITS['sources']} sources")
        clean = []
        for j, src in enumerate(srcs):
            role = src.get("role") if isinstance(src, dict) else None
            if role not in SOUNDS:
                raise ValueError(f"{where} source {j + 1}: role {role!r} is not one of {sorted(SOUNDS)}")
            snd = SOUNDS[role]
            try:
                az = float(src.get("az", 0)) % 360
                el = _clamp(float(src.get("el", snd["el"])), *LIMITS["el"])
                level = float(src.get("level_db", sum(snd["level_db"]) / 2))
            except (TypeError, ValueError):
                raise ValueError(f"{where} source {j + 1}: az, el and level_db must be numbers")
            if not LIMITS["level_db"][0] <= level <= LIMITS["level_db"][1]:
                raise ValueError(f"{where} source {j + 1}: level_db {level} outside {LIMITS['level_db']}")
            clean.append({"role": role, "az": round(az, 1), "el": round(el, 1), "level_db": round(level, 1),
                          "target": bool(src.get("target", snd["target"]))})
        weight = _clamp(float(s.get("weight", 1)), *LIMITS["weight"])
        out.append({"name": str(s["name"])[:60], "why": str(s.get("why", ""))[:200], "weight": weight,
                    "tags": [str(t)[:24] for t in s.get("tags", [])][:8], "sources": clean})
    return {"source": str(d.get("source", "unspecified"))[:120], "scenes": out}


def suggest_scenes(needs, max_scenes=9):
    """A first scene set from a needs profile ({activities, goals, priorities, requirements, free_text},
    the agents' NeedsProfile): scenes whose tags match words in the needs, priorities weighted higher,
    always anchored by Conversation. Each scene says which need called for it."""
    def words(key):
        v = needs.get(key) or []
        return [v] if isinstance(v, str) else list(v)
    lines = [(t, "priority") for t in words("priorities")] + [(t, "need") for k in ("activities", "goals", "requirements")
                                                              for t in words(k)]
    if str(needs.get("free_text", "")).strip():
        lines.append((needs["free_text"], "need"))
    chosen = {}
    for text, kind in lines:
        tags = {t for pat, ts in NEEDS.items() if re.search(pat, text.lower()) for t in ts}
        overlap = {sc["name"]: len(tags & set(sc["tags"])) for sc in LIBRARY}
        best = max(overlap.values(), default=0)
        for sc in LIBRARY:
            if best and overlap[sc["name"]] == best:            # the scenes that fit this need best
                w = 2.0 if kind == "priority" else 1.0
                c = chosen.setdefault(sc["name"], {**sc, "weight": 0.0, "because": []})
                c["weight"] = max(c["weight"], w)
                if text not in c["because"]:
                    c["because"].append(text)
    base = next(s for s in LIBRARY if s["name"] == "Conversation")
    chosen.setdefault("Conversation", {**base, "weight": 1.0, "because": ["everyday speech (always included)"]})
    ranked = sorted(chosen.values(), key=lambda s: (-s["weight"], LIBRARY.index(next(l for l in LIBRARY if l["name"] == s["name"]))))
    scenes = [{"name": s["name"], "weight": s["weight"], "tags": s["tags"], "sources": s["sources"],
               "why": f"{s['why']}; for: {', '.join(s['because'][:3])}"} for s in ranked[:max_scenes]]
    return validate_scene_set({"source": "suggested from needs (hornsim.scene_spec.suggest_scenes)", "scenes": scenes})


def as_scenarios(scene_set):
    """The set as the agents' ScenarioSpec records (scenario_id, description, source_level_db_spl, tags)."""
    return [{"scenario_id": re.sub(r"[^a-z0-9]+", "_", s["name"].lower()).strip("_"),
             "description": s["why"] or s["name"],
             "source_level_db_spl": max(src["level_db"] for src in s["sources"] if src["target"]) if any(src["target"] for src in s["sources"]) else None,
             "tags": s["tags"]} for s in scene_set["scenes"]]


def vocabulary():
    """What the research step may use, as JSON: sounds, limits, the scene format and example scenes."""
    return {"sounds": {k: {**v, "level_db": list(v["level_db"])} for k, v in SOUNDS.items()},
            "limits": {k: (list(v) if isinstance(v, tuple) else v) for k, v in LIMITS.items()},
            "frame": "az 0 front, 90 right ear side, 180 behind, 270 left ear side; el degrees up; level_db dB SPL at the head",
            "scoring": "per scene and ear: SII for speech targets, audibility index (energy-weighted bands) for other targets; "
                       "the earpiece target is the importance-weighted audibility gap across scenes (weights = scene weight)",
            "scene_format": {"name": "str", "why": "str: why this user needs it", "weight": "0-10", "tags": ["str"],
                             "sources": [{"role": "one of sounds", "az": "deg", "el": "deg", "level_db": "dB SPL", "target": "bool"}]},
            "examples": LIBRARY[:3]}


if __name__ == "__main__":
    print(json.dumps(suggest_scenes(json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}), indent=1))
