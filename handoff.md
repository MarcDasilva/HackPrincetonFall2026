# Passive Horn Hearing Device — Build Handoff

Nov 14, 2026 · @marc

## The idea

We design a passive, battery-free hearing device — a printed acoustic horn — whose geometry is optimized per patient against a biophysical model of their own cochlea.

A passive horn has roughly 15 dB of gain to spend, in a narrow band. There is no DSP to correct it afterward, so the geometry *is* the prescription. Our agent decides where that gain goes.

**Pitch:** *A passive hearing device has about 15 dB of gain to spend. We built the layer that decides where it goes — by simulating the patient's own auditory nerve and searching thousands of horn geometries for the one that gets it closest to normal hearing.*

## Why the problem exists

Purely passive, 3D-printed acoustic amplification tops out around 10–20 dB of gain in narrow frequency bands, against the 30–60 dB of programmable gain a digital hearing aid delivers ([Dhow Dispatch](https://dhowdispatch.beehiiv.com/p/dhow-dispatch-amano-labs-the-20-hearing-aid-question)).

That limit is the entire design problem. Spend the band at 500 Hz for a patient whose loss sits at 3 kHz and the device does nothing — and there is no software stage to fix it.

**Prior art.** [Amano Labs](https://homegrown.co.in/homegrown-voices/amano-labs-wants-to-make-hearing-aids-more-accessible-one-20-device-at-a-time) (McMaster students, pre-order stage) sells a $19.99 mechanically amplified device. Users submit a photograph of their ear, which software maps to produce a custom fit, manufactured from 3D-printed components. They proved the manufacturing and distribution model.

**Our wedge.** They fit the device to the ear's *shape*. Nobody optimizes the gain band against the patient's *hearing loss*, scored on a model of their cochlea. That is the open problem and it is purely computational.

**Design equation, already known.** Horn acoustics give a direct geometry → gain-band mapping. A 1 mm² throat with a 22.2 mm² mouth yields up to 13.4 dB; an effective length of 186.8 mm sets a 459 Hz cutoff, with efficient gain from about 688 Hz — and speech above ~688 Hz is what many hearing-impaired listeners lose ([patent US11743635](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11743635)).

## Architecture

[embed: node/a2c0cbc9-454f]

Every box in the middle row is an existing Python package, not something we write. The agent orchestrates them.

**The load-bearing decision is the manifest.** Because the agent writes a results file instead of serving an API, the frontend is a static reader — no backend, no latency, and no way for the demo to fail live in front of judges.

## The screen

Four panels on one page. The test is whether a judge understands the product without being told what they are looking at.

```
┌──────────────────────────────┬──────────────────────────┐
│  [photo] → 3D EAR            │  EAR PROFILE             │
│          (rotatable)         │  · audiogram             │
│  agent's horn snaps in here  │  · where hearing is lost │
│                              │  · canal uncertainty band│
├──────────────────────────────┴──────────────────────────┤
│  COCHLEA   reference neurogram  |  this ear's neurogram │
├─────────────────────────────────────────────────────────┤
│  100 EXPERIMENTS   ▸ click any one to hear it           │
├─────────────────────────────────────────────────────────┤
│  ▶ unaided       ▶ this design       ▶ agent's pick     │
└─────────────────────────────────────────────────────────┘
```

**Top left — the ear.** A photo goes in, AudioEar returns a pinna mesh, three.js renders it rotatable. The agent's chosen horn renders beside it in the same scene, so the fit is visible rather than asserted.

**Top right — the profile.** Audiogram, the frequency region where this ear has lost sensitivity, and the canal volume band we could not measure. This panel is the reason the design is personalized — without it the horn is just a cone.

**Middle — the cochlea.** Two neurogram heatmaps side by side: healthy reference, and this ear. The distance between them *is* the reward. Clicking an experiment swaps the right heatmap to that design's result.

**Bottom — the experiments and the audio.** A hundred horn geometries as a clickable strip, scored and sorted. Click one and its mesh loads beside the ear, its neurogram replaces the right heatmap, and its audio becomes playable. The three buttons play unaided, the selected design, and the agent's pick back to back. That comparison is the demo.

## Results manifest

The agent does not serve an API. It writes one file, and the frontend is a pure reader of it.

```json
{
  "ear": {
    "mesh": "ear.glb",
    "audiogram": [[250, 15], [500, 20], [1000, 30], [2000, 45], [4000, 55]],
    "canal_band": { "volume_cc": [0.5, 0.9], "samples": 32 },
    "cohc": 0.3,
    "cihc": 0.6
  },
  "reference_neurogram": "ref.png",
  "unaided": { "neurogram": "ng_unaided.png", "audio": "aud_unaided.wav" },
  "experiments": [
    {
      "id": 7,
      "mesh": "horn_007.glb",
      "params": { "throat_mm2": 1.2, "mouth_mm2": 20.4, "length_mm": 180, "vents": 2 },
      "gain_curve": [[250, 1.1], [500, 4.0], [1000, 9.2], [2000, 12.8]],
      "neurogram": "ng_007.png",
      "audio": "aud_007.wav",
      "score": 0.72
    }
  ],
  "pick": 43
}
```


| Panel            | Reads                                                              |
| ---------------- | ------------------------------------------------------------------ |
| 3D ear           | `ear.mesh`                                                         |
| Ear profile      | `ear.audiogram`, `ear.canal_band`                                  |
| Cochlea, left    | `reference_neurogram`                                              |
| Cochlea, right   | `unaided.neurogram`, then `experiments[i].neurogram`               |
| Experiment strip | `experiments[*].score`, `.id`                                      |
| Horn beside ear  | `experiments[i].mesh`                                              |
| Audio buttons    | `unaided.audio`, `experiments[i].audio`, `experiments[pick].audio` |


Roughly 30 MB in total: one ear mesh, 100 small horn meshes, 101 PNGs, 101 short WAVs. All of it generated offline before the demo, so nothing can time out in front of judges.

## Tech stack


| Component                           | Package                                              | Notes                                                                                                                                                                          |
| ----------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Photo → 3D pinna                    | [AudioEar](https://arxiv.org/abs/2301.12613)         | PyTorch. 2,000 annotated 2D images, 112 ground-truth 3D scans, code public                                                                                                     |
| Cochlea model                       | [brucezilany](https://pypi.org/project/brucezilany/) | Bruce-Zilany-Carney auditory nerve model; `inner_hair_cell`, `synapse`, multi-threaded `Neurogram` class                                                                       |
| Cochlea model (alternative)         | [cochlea](https://pypi.org/project/cochlea)          | `run_zilany2014()`; sound in, spikes out; scales to thousands of fibers                                                                                                        |
| Neurogram → audio                   | [neurovoc](https://pypi.org/project/neurovoc/)       | For the demo and ASR cross-check                                                                                                                                               |
| Audiograms, HASPI, hearing-loss sim | [pyclarity](https://pypi.org/project/pyclarity)      | HASPI v2 takes signal + reference + audiogram → 0–1; also MSBG loss simulator and NAL-R                                                                                        |
| Horn acoustics                      | **Your code**                                        | Webster horn as chained 2×2 transmission matrices in `numpy`; \~100 lines, microseconds                                                                                        |
| Canal uncertainty sampling          | `scipy.stats.qmc`                                    | Latin hypercube; residual volume ranges 0.5 / 0.7 / 0.9 cc ([source](https://hearingreview.com/2006/07/where-an-accurate-fitting-begins-assessment-of-in-situ-acoustics-aisa)) |
| Real ear anatomy (optional)         | [OpenEar](https://zenodo.org/records/1473724)        | 8 segmented human temporal bones, free; scala tympani included; 4–14 GB per specimen                                                                                           |
| Occlusion mitigation                | metamaterial cavity lattice                          | [meta-earplug precedent](https://www.scientificamerican.com/article/new-earplugs-wont-amplify-the-sound-of-your-own-voice/): 85% of participants preferred it                  |
| Agent layer                         | LangChain deepagents                                 | Planner, subagents, filesystem                                                                                                                                                 |
| Optimizer inside stages             | `pycma` or `scikit-optimize`                         | CMA-ES or Bayesian                                                                                                                                                             |
| Surrogate                           | `scikit-learn` GradientBoosting                      | Avoids re-running the cochlea model                                                                                                                                            |
| Geometry → STL                      | `build123d` / `CadQuery` + `trimesh`                 | Parametric horn, boolean the channels                                                                                                                                          |
| Demo frontend                       | `three.js`, HTML5 audio, `plotly`                    | Horn render, three listening buttons, neurogram heatmaps                                                                                                                       |
| Mesh export                         | trimesh → glTF                                       | STL for printing, .glb for the browser; 100 horns are a few hundred KB each                                                                                                    |
| Manifest                            | plain JSON                                           | No backend, no server, no live compute. Written once by the agent, read by the frontend                                                                                        |


## Design space

The shell stays standard. Only the acoustic coupling — the horn — is personalized. It is a small passive part, cheap to print, and it is where the acoustics actually live.


| Parameter                    | Range                                         | What it controls                      |
| ---------------------------- | --------------------------------------------- | ------------------------------------- |
| Throat area                  | printable min upward                          | Gain magnitude (with mouth area)      |
| Mouth area                   | constrained by concha volume                  | Gain magnitude, low-frequency reach   |
| Length                       | shell → tip distance                          | Cutoff frequency                      |
| Flare profile                | 3–4 control points, area vs. position         | Gain curve shape and ripple           |
| Tip seal                     | sealed → open dome                            | Occlusion vs. low-frequency retention |
| Vent count                   | 1–4                                           | Occlusion relief                      |
| Vent diameters               | printable min upward                          | Low-frequency leakage                 |
| Damper resistance / position | discrete standard values, position along bore | Smooths standing-wave peaks           |
| Metamaterial cavities        | lattice geometry                              | Own-voice boom suppression            |


Ten-ish continuous parameters, all printable, all computable in microseconds. Non-circular and free-form flare profiles are in scope precisely because printing removes the stock-insert constraint that made them untestable.

## Reward function

The objective is neural, not spectral: **how close does the device get this patient's auditory nerve to firing like a healthy one?**

- **Reference:** clean speech → healthy cochlea model → reference neurogram
- **Achieved:** speech → horn → impaired cochlea model → achieved neurogram
- **Gap:** spectro-temporal distance between the two

```latex
r = -\overline{\mathrm{gap}} \;-\; \lambda_1 \cdot \mathrm{CVaR}_{\mathrm{worst}}(\mathrm{gap}) \;-\; \lambda_2 \cdot \overline{\mathrm{occlusion}} \;-\; \lambda_3 \sum \max(0,\, \mathrm{fb}_{\mathrm{limit}} - \mathrm{fb}_{\mathrm{margin}})
```

The CVaR term is what makes this a robustness result rather than an averaging one: the agent is penalized for designs that fail on the unlucky canals, which is the real-world failure mode.

Hearing loss enters the cochlea model through outer and inner hair-cell health scalars (`cohc`, `cihc`), so the patient's impairment is set directly rather than approximated. Both names are confirmed in the package, and the mapping is usable as-is: `cohc = 0.3` yields roughly mild loss — about 15 dB of threshold shift at 500 Hz rising to 30 dB at 2 kHz — which is exactly the band a passive horn can address.

Cross-check only, not the primary signal: HASPI from `pyclarity`, and ASR word error rate on `neurovoc`-reconstructed audio.

## The evaluation funnel

[embed: node/fa696716-a9cf]

Total compute stays roughly flat per stage, which is what makes the funnel efficient rather than merely sequential. Stages 1–3 are your own code and do 99.9% of the filtering, so build them first and make them fast.

## The agent layer

The agent does three things a numeric optimizer cannot.

1. **Reads the shape of the gap.** The neurogram shows *where* in frequency and time the impaired ear diverges from healthy. The planner reasons about it — "the deficit is concentrated at 2–4 kHz, low frequencies are intact, so spend the band high and open the vent" — and chooses a design region accordingly.
2. **Diagnoses which constraint is binding.** If 99.9% of candidates die at the gain gate, the target may be infeasible for this ear: loosen the feedback constraint, revisit length, or flag that this patient needs a powered device. That is a judgment about the problem, not a step in the search.
3. **Reallocates its own budget.** Whether to spend more compute on full-neurogram evaluation or go back and widen the generator is a decision about where the remaining uncertainty lives.

Mechanically: planner holds the hypothesis file, a subagent runs the Monte Carlo batch and returns the score vector, the filesystem accumulates which trade-offs worked for which gap shapes.

## Build order

Two checkpoints validate the physics. Do not build past them. After that, the ordering principle is unusual and deliberate: **the screen gets built before the search does**, against a hand-written manifest. The frontend is the only thing judges see, and it is the thing most likely to eat a day.

- **Checkpoint 1 — the acoustics.** Chain conical sections into a transmission matrix and compute the gain curve. A flared horn must show high-frequency boost relative to a uniform tube. If it does, the physics is right and the search is trustworthy.
- **Checkpoint 2 — the cochlea.** Run one speech clip through `brucezilany` twice: once healthy, once with `cohc` / `cihc` set to this patient's loss. The gap must look like the loss you put in. If it does, the reward is real.
- Wire 1 into 2 — gain curve applied to the clip, clip into the cochlea model. That is the environment step, and the whole project rests on it.
- Freeze the manifest schema. Commit a hand-written `results.json` with three fake experiments and three placeholder meshes.
- **Build the frontend against the fake manifest.** All four panels, all reading from the file. Nothing downstream can break it after this point.
- Add canal sampling and the CVaR term
- Add the funnel gates, cheapest first
- Run the 100-experiment sweep: export glTF horns, render neurograms, vocode audio, write the real manifest over the fake one
- Add the agent layer on top of the working funnel
- Record a screen capture of the finished demo as a fallback

Cost discipline is non-negotiable. Inner loop: ~30–40 characteristic frequencies, hsr fibers only, 1-second clips. Validation: ~100 CFs, all three fiber types, top ~50 designs. The demo pass runs once, at full resolution, offline — it is the only place rendering cost is allowed to be high, because nobody is waiting on it. BEM for the pinna HRTF runs once per ear and is cached; never in the loop.

## Risks and what not to claim

**Unverified dependencies.** Check these installs before committing: Mesh2HRTF, `pycma`, `build123d`. The `cohc` / `cihc` names in `brucezilany` are confirmed, so the reward path is no longer a risk. The AudioEar model release should be smoke-tested early — if it fights you, fall back to using its 112 ground-truth 3D scans directly as your population and skip reconstruction entirely.

**HASPI is stochastic.** It employs random thresholding noise, so scores are not reproducible unless the seed is set. Fix seeds per scene or the agent will chase noise.

**A photo cannot see the ear canal.** This is a hard physical limit, acknowledged in the AudioEar paper itself, which covers only the visible pinna. We handle it by treating the canal as a distribution rather than pretending to measure it — which is also the correct engineering answer, since in-situ vent effect cannot be predicted from dimensions and can only be measured once the device is in the ear.

**What not to claim.** We predict acoustic and neural performance; we do not validate on real ears. Claim the *method* and the robustness framing. State explicitly that in-situ verification is still required and that a passive device targets mild-to-moderate loss only. Do not position this as beating Amano — position it as the optimization layer the category lacks.

**Do not invent numbers.** Every figure in this doc is sourced. If a cost or benefit figure is wanted for the pitch, derive it or leave it out.

## Sources

The anchor is Bruce, Sachs &amp; Young, *JASA* 113(1):369–388 (2003). It states that extensive experimental testing of potential hearing aids is infeasible, and then shows that this auditory-nerve model predicts how frequency-shaping amplification changes nerve responses. The search it implies was proposed in 2003 and, as far as we can find, nobody ran it. That is the gap this project fills.

- [Bruce, Sachs &amp; Young (2003)](https://pubs.aip.org/asa/jasa/article/113/1/369/546836) — the model-based hearing-aid design argument
- [AudioEar (arXiv 2301.12613)](https://arxiv.org/abs/2301.12613) — photo → 3D pinna, code and data public
- [brucezilany](https://pypi.org/project/brucezilany/) — the auditory-nerve model we score against
- [Patent US11743635](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11743635) — passive horn geometry → gain-band mapping with worked numbers
- [Amano Labs](https://homegrown.co.in/homegrown-voices/amano-labs-wants-to-make-hearing-aids-more-accessible-one-20-device-at-a-time) — the $19.99 passive device and photo-based fit
- [Dhow Dispatch](https://dhowdispatch.beehiiv.com/p/dhow-dispatch-amano-labs-the-20-hearing-aid-question) — the 10–20 dB passive ceiling
- [OpenEar](https://zenodo.org/records/1473724) — 8 segmented human temporal bones, free
- [In-situ acoustics](https://hearingreview.com/2006/07/where-an-accurate-fitting-begins-assessment-of-in-situ-acoustics-aisa) — residual canal volume ranges, and why vent effect can only be measured in the ear
- 