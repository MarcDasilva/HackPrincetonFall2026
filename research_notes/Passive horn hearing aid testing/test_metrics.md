# Hearing aid fitting and evaluation metrics: which can be simulated for a passive 3D-printed in-concha horn

Scope note: a passive horn has no compression, no noise reduction, and no battery. It is a fixed, level-independent linear filter, plus whatever it does to the ear's own concha and canal resonances. Many clinical caveats exist because modern aids are nonlinear. Those caveats mostly do not apply here, and that changes which metrics are defensible. Facts marked "(not verified this session)" come from background knowledge, not from a source fetched here. Treat them as leads to check.

## 1. Real-ear measurement (REUR, REAR, REIG, REOG, RECD) and verification against prescriptive targets

### Takeaway
REIG = REAR - REUR is the clinical gold standard for verifying a fit against a target such as NAL-NL2 or NAL-R. The usual pass criterion is within about ±5 dB of target per frequency. For a passive linear horn, the simulated insertion-gain curve maps directly onto REIG. It is the most defensible primary output, provided the model subtracts the open-ear (REUR) resonance that the device removes.

### Cited Findings
- REIG = REAR - REUR. Insertion gain is aided ear-canal SPL minus unaided ear-canal SPL. REUR is the SPL in the open, unaided canal and reflects the canal's own resonance. REAR is the probe-tube SPL with the aid and its coupling in place and switched on. — [Hearing Review, Integrated REM](https://hearingreview.com/practice-building/practice-management/integrated-rem-real-ear-measurement-from-a-hearing-aid); [Canadian Audiologist, Quick answers](https://canadianaudiologist.ca/?p=14459)
- RECD is the dB difference across frequency between SPL at the eardrum and SPL in a 2-cc coupler. Once measured, it converts any coupler response into a predicted real-ear response. — [Canadian Audiologist, REM feature](https://canadianaudiologist.ca/real-ear-measurement-feature/?output=pdf); [Oticon Real Ear Cookbook](https://www.oticon.com/~/media/Oticon%20US/main/Download%20Center/Opn/Product%20Information/12241%20-%2015555-10026%20Real%20Ear%20Cookbook.pdf)
- More open fittings keep more of the residual canal resonance, so a given REIG target needs less device gain than with an occluding fit. This is why REUR subtraction matters, and why it is debated for non-occluding fits. — [Hearing Review, REM for non-occluding fittings](https://hearingreview.com/hearing-loss/patient-care/hearing-fittings/demystifying-rem-verification-for-non-occluding-fittings)
- Tolerance: clinical guidance is to keep adjusting until real-ear output is within 5 dB of target at each frequency, with a contour that matches the target. Cox & Alexander (1990) found that the differences between prescriptions were preserved when the RMS error to target was 5 dB or less. — [AudiologyOnline, Research QuickTakes Vol 6](https://www.audiologyonline.com/articles/research-quicktakes-volume-6-pt-28708-28708)
- Attainment in practice: more than 84% of fittings for mild-to-moderate losses were within 5 dB at all test levels. Severe-to-profound fittings deviated most from target and had the highest RMSE. This was a DSL v5 pediatric study. — [J Am Acad Audiol 2020;31(5):354-362](https://www.thieme-connect.de/products/ejournals/html/10.3766/jaaa.19057)
- High frequencies are harder to match. In a manufacturer poster, 83.2% of ears were within ±5 dB from 250 to 3000 Hz, but only 62.0% from 4000 to 6000 Hz. Treat this with caution: it is manufacturer data. — [Starkey e-STAT 2.0 / NAL REAR poster (JDVAC 2025)](https://cdn.mediavalet.com/usil/starkeyhearingtech/bx7nNMoJXkeGdF5clHzMsw/bdNwzROR2k2SXnbpLgaxYA/Original/JDVAC%202025%20ESTAT%20and%20NAL%20REAR%20Poster.pdf)
- When the fitting software is set to "NAL-NL2", the resulting real-ear output differs significantly from NAL-NL2 targets across three manufacturers. This is the main argument for verifying by measurement rather than trusting the software. — [Hearing Review 2015, Manufacturers' NAL-NL2 fittings fail real-ear verification](https://hearingreview.com/2015/02/manufacturers-nal-nl2-fittings-fail-real-ear-verification)
- A personal notes site claims that fits within ±5 dB of NAL-NL2 give better speech-in-noise outcomes, citing Aazh & Moore 2007 and Valente et al. 2018. I could not verify this against the primary papers. — [notes-1jv.pages.dev, REIG and prescription targets](https://notes-1jv.pages.dev/tools-of-audiology/real-ear-measurement/reig-and-targets)

### Inferences
- A passive horn has gain that does not depend on level, so one simulated REIG curve holds at 50, 65 and 80 dB SPL. NAL-NL2 and DSL v5 are nonlinear prescriptions with level-dependent targets. A linear device can match at most one input level, normally 65 dB SPL. **NAL-R** (linear, Byrne & Dillon 1986; not verified this session) is the natural target for a passive device. The HASPI v2 training data also amplified hearing-impaired listeners' stimuli with NAL-R (see section 3), which makes NAL-R internally consistent with the HASPI scoring.
- Recommended headline fitting metric: RMS error between simulated REIG and the NAL-R target over 0.5-4 kHz, plus the share of audiometric frequencies within ±5 dB. Judges who know audiology will recognize both. The ±5 dB tolerance is the clinical norm.
- The simulation has to model insertion gain, not raw horn transfer gain. A device in the concha changes or removes the natural concha and canal resonance (REUR). A horn with 10 dB of transfer gain at 3 kHz can show near-zero or negative REIG there if it kills the open-ear peak. The pipeline should compute REAR(horn in place) - REUR(open ear from the same mesh), both at the eardrum position.
- Real-world verification path, if a printed prototype exists: an off-the-shelf probe-mic REM system measures REUR and REAR directly. A KEMAR or 3D-printed ear simulator with a coupler microphone would give a bench REAG/REIG check.

### Gaps
- I found no published validation of REIG predicted from FEM/BEM acoustic simulation of a patient-specific ear mesh against probe-mic REIG. Plausible accuracy, especially above about 4 kHz where small geometry errors matter most, is unknown.
- I did not confirm the NAL-R formula, or NAL-NL2 target tolerances from official NAL or BSA documents.
- The practical maximum gain of a passive concha-sized horn, and how it compares with typical NAL-R targets for moderate loss, was not researched. It will limit which audiograms the device can fit.

## 2. Speech Intelligibility Index (ANSI S3.5-1997)

### Takeaway
SII is the cheapest defensible metric: a closed-form calculation from band speech level, band noise level, and hearing thresholds, taking microseconds. It is standardized and widely recognized. It measures audibility, not intelligibility, and it overpredicts performance for severe losses, steep losses and high sensation levels.

### Cited Findings
- SII is defined in ANSI/ASA S3.5-1997 (R2020). It replaced the Articulation Index and is computed as the sum over bands of band importance times band audibility. Inputs are equivalent speech spectrum level, equivalent noise spectrum level, and equivalent hearing threshold level. — [ANSI Blog, Speech Intelligibility Index](https://blog.ansi.org/speech-intelligibility-index)
- The standard provides importance functions for several speech materials (Annex B) or user-supplied band weights. It allows critical-band, one-third-octave, equally-contributing-critical-band, and octave-band methods. The R `SII` package implements it, including a speech level distortion factor and an optional hearing-loss desensitization factor (Ching et al. 2011; Johnson 2013), which is off by default. — [R SII package docs](https://rdrr.io/cran/SII/man/sii.html); [SII package vignette](https://rdrr.io/cran/SII/f/inst/doc/SII.pdf)
- SII runs from 0 to 1 and gives the proportion of the speech signal that is audible. Aided SII is used clinically to judge access to speech. Children with mild to moderately severe loss and aided SII below 0.65 showed greater vocabulary delays. — [E3 Diagnostics, SII](https://e3diagnostics.com/blog/speech-intelligibility-index); [AudiologyOnline, Beyond Speech Intelligibility](https://www.audiologyonline.com/articles/beyond-speech-intelligibility-expanding-clinician-29406)
- Main known limit: Ching, Dillon & Byrne (1998, JASA) found that audibility alone does not explain speech recognition for many hearing-impaired listeners. Departures from audibility-based predictions are largest for severe losses at high sensation levels. Later work reports little benefit from added high-frequency audibility once high-frequency loss exceeds about 55 dB HL (Hogan & Turner 1998). — [Macquarie Univ. record, Ching et al. 1998](https://researchers.mq.edu.au/en/publications/speech-recognition-of-hearing-impaired-listeners-predictions-from/); [ASHA JSLHR 2008](https://pubs.asha.org/doi/10.1044/1092-4388(2008/057)); [PMC6688860](https://pmc.ncbi.nlm.nih.gov/articles/PMC6688860)
- SRT prediction accuracy: across 315 audiograms, individualized FADE and SII predicted SRTs with RMSE of 5.6 and 6.8 dB. SII error was much larger for steep losses (RMSE 22.6 dB). A model with individualized cochlear bandwidth, compression and STM sensitivity beat SII, but did no better than a simpler linear model. — summarized in [arXiv 2203.09148](https://arxiv.org/pdf/2203.09148) and [J Am Acad Audiol 2013;24(4):307-328](https://www.thieme-connect.com/products/ejournals/pdf/10.3766/jaaa.24.4.6.pdf)
- SII change predicted self-reported benefit on APHAB and HHIE-A once unaided SII was controlled for. — [Kim et al., AAS 2016 poster (Univ. Iowa)](https://haar.lab.uiowa.edu/sites/haar.lab.uiowa.edu/files/2022-08/Kim%20et%20al%20AAS%202016.pdf)
- SII needs separate speech and noise signals or spectra. STOI and HASPI need clean and degraded speech. — [arXiv 2203.09148](https://arxiv.org/pdf/2203.09148)

### Inferences
- For a linear passive device, aided SII is easy to compute from the insertion-gain curve: speech band level + REIG vs threshold + noise band level. It works at all three presentation levels and for speech-shaped noise at +5 dB SNR. SII is level-dependent through threshold and the level distortion factor, so it does reward the device at 50 dB SPL and properly penalizes 80 dB SPL.
- Use SII as the fast inner-loop objective for optimizing horn geometry. Use HASPI as the slower confirmation score. Report both as aided-minus-unaided deltas.
- SII cannot see temporal-envelope effects. Babble fluctuations, reverberation and the horn's own resonant ringing are invisible to it. It also overrates high-frequency gain for steep or severe losses. That is a reason to enable the desensitization factor, or to cap credit where thresholds exceed about 55 dB HL.

### Gaps
- I did not obtain the band-importance tables or the exact level distortion formula from the standard itself, since ANSI S3.5 is paywalled. The R package and Python ports implement them.
- I found no published SII cutoff for "adequate" adult aided audibility comparable to the pediatric 0.65 figure.

## 3. HASPI v2 / HASQI

### Takeaway
HASPI v2 (Kates & Arehart 2021) is an intrusive intelligibility metric. It runs clean reference and degraded speech through a hearing-loss-aware auditory periphery model, then maps envelope-modulation fidelity to proportion of sentences correct. It is accurate on the data it was fit to (r about 0.94-0.97 for noise, distortion and reverberation). On unseen hearing-aid listener data (Clarity CPC2) it is much weaker: RMSE 28.7 percentage points, r = 0.70. It is the best-known open metric for this use and runs in pyclarity.

### Cited Findings
- Citation: Kates & Arehart, "The Hearing-Aid Speech Perception Index (HASPI) Version 2," Speech Communication 131:35-46 (2021), doi 10.1016/j.specom.2020.05.001. Compared with v1 on five datasets, it had significantly lower RMS error on most of them and was significantly more accurate for reverberation. — [researchr bibtex](https://researchr.org/publication/KatesA21/bibtex); [AMiner record](https://aminer.org/pub/5fae6c34d4150a363ce940fc/the-hearing-aid-speech-perception-index-haspi-version)
- Model structure, as described in Kates 2023: a 24 kHz peripheral model with a 32-band gammatone filterbank from 80 to 8000 Hz, outer-hair-cell compression and inner-hair-cell attenuation set from the audiogram, and adaptation. Sub-threshold levels are floored at 0 dB SL. Envelopes are lowpassed at 320 Hz, projected onto 5 cepstral basis functions, and passed through 10 modulation filters from 2 to 256 Hz. A bagged ensemble of 10 small neural networks (one hidden layer, 4 neurons) outputs a value bounded to [0, 1]. — [Kates 2023, JASA 153(3):1662-1673, PMC10257526](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)
- Training data: five datasets (noise plus nonlinear distortion, frequency compression, ideal-binary-mask noise suppression, reverberation, noise vocoding), with NH and HI listeners. HI listeners' stimuli were amplified with **NAL-R**. NH stimuli were at 65 dB SPL, reverberation at 70 dB SPL. — [PMC10257526](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)
- Fit accuracy for v2 sentences correct (bootstrap means): noise and distortion NH+HI r = 0.956, RMSE 0.097 (HI only r = 0.974); frequency compression r = 0.966; IBM r = 0.973; reverberation r = 0.972, RMSE 0.081. Noise vocoder within groups is weak: NH r = 0.44, HI r = 0.52. — [PMC10257526, Table II](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)
- Caveats from Kates 2023:
  - HASPI depends on the audibility of the amplified speech as well as envelope fidelity, so changing the amplification rule can change the fitted behavior.
  - Hearing loss alone produces predicted errors even in quiet. The high-SNR ceiling falls with greater loss, from 0.946 for audiogram S2 to 0.636 for N6.
  - Output is biased at very low SNR (about 0.004 rather than 0).
  - Within-group correlations are weak where intersubject variability dominates.

  — [PMC10257526](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)
- Clarity Prediction Challenge 2 baseline: HASPI plus a sigmoid fitted on training data, predicting HI listeners' sentence intelligibility for hearing-aid-processed signals. Baseline RMSE 28.7 and r = 0.70. The best entry reached RMSE 25.1 and r = 0.78. — [Clarity CPC2 baseline](https://claritychallenge.org/docs/cpc2/cpc2_baseline); [Clarity CPC2 results](https://claritychallenge.org/docs/cpc2/cpc2_results)
- Level calibration in pyclarity: the HASQI v2 function takes `level1`, the dB SPL that corresponds to RMS = 1, with a default of 65 dB SPL. — [clarity hasqi.py](https://github.com/claritychallenge/clarity/blob/main/clarity/evaluator/hasqi/hasqi.py)
- Stochasticity: a Clarity PR refactoring HAAQI notes that outputs differ from the previous implementation because "random noises are generated in a different order". The ear model therefore uses random noise, and scores are not bit-reproducible unless the RNG is seeded. — [clarity PR #364](https://github-redirect.dependabot.com/claritychallenge/clarity/pull/364)
- A HASQI v2 publication exists (AES e-library). — [AES elib 17126](https://www.aes.org/e-lib/browse.cfm?elib=17126). Its validation figures were not retrieved.
- A binaural HASPI was published in 2025. — [Acta Acustica 2025](https://acta-acustica.edpsciences.org/10.1051/aacus/2025054)

### Inferences
- A passive linear horn with NAL-R-like shaping is very close to the regime HASPI v2 was trained on (NAL-R-amplified HI listeners, additive noise, reverberation). It is a more in-distribution use than scoring an exotic nonlinear algorithm, which strengthens the case for HASPI here.
- Reference choice: use the clean, unamplified speech at the same presentation level as the reference, scored by HASPI's normal-hearing model. Feed the horn-filtered noisy mixture as the processed signal with the patient audiogram. Score the unaided condition the same way, with the open-ear REUR included or a flat filter, and report the delta. HASPI is not invariant to presentation level, so it must be scored at 50, 65 and 80 dB SPL with `level1` set consistently. Mis-set `level1` silently changes audibility.
- Seed the RNG and average over several noise tokens or clips. Treat score differences below about 0.02 as noise until the run-to-run spread has been measured.
- Report HASPI in the logistic/probability domain, but note the CPC2 accuracy: about ±29 percentage points RMSE on unseen data. It ranks designs, but it is not an absolute predictor of a patient's score.
- HASQI v2 can be added cheaply as a sound-quality check. A horn with sharp resonances may score well on HASPI and poorly on HASQI, which flags a "tinny" or "honky" sound. This guards against overfitting a resonance to the audiogram.
- Runtime: one HASPI call on a 3-5 s clip is on the order of a second or less in Python. This is plausible but not benchmarked this session.

### Gaps
- I did not get the original 2021 paper's full text, so its exact v1-vs-v2 RMSE numbers are missing. The v2 table above comes from Kates 2023.
- I did not confirm whether pyclarity's `haspi_v2` exposes a seed argument. Check the source.
- HASQI v2's correlation with quality ratings was not retrieved.

## 4. Speech-in-noise tests (QuickSIN, HINT, WIN, DIN) and model-based SRT

### Takeaway
Clinical speech-in-noise tests estimate SRT50, the SNR for 50% correct. SNR loss is the patient's SRT minus the normal-hearing SRT. Sweeping SNR through a model (SII, HASPI, STOI) and interpolating the 50% point is a common research practice for predicting SRTs, with reported errors of about 5-7 dB RMSE across audiograms. A "simulated SRT shift with the horn" is defensible as a research proxy, but not as a clinical score.

### Cited Findings
- QuickSIN: 6 sentences per list, SNR falling from 25 to 0 dB in 5 dB steps, 5 key words each. SNR loss = 25.5 - total words correct. The 25.5 comes from an SNR-50 estimate of 27.5 minus the 2 dB that normal-hearing listeners need. — [Interacoustics QuickSIN](https://www.interacoustics.com/academy/audiometry-training/speech-audiometry/quicksin); [Etymotic QuickSIN manual](https://manualzz.com/manual/Etymotic/QuickSIN%2520Speech-in-Noise%2520Test)
- QuickSIN severity bands: 0-3 dB normal or near normal, 3-7 dB mild, 7-15 dB moderate, over 15 dB severe SNR loss. — [HearingTracker expert answer](https://www.hearingtracker.com/expert_answers/1298); [GN Otometrics OtoSuite QuickSIN guide](https://bioclinicalservices.com.au/gn-otometrics/clinical/otosuite-and-the-quicksin-module-user-guide-rev-01-oct-2012)
- DIN: digit triplets in steady noise, adaptive 1-up/1-down with 2 dB steps, SRT = mean SNR of the last 21 trials. Normal-hearing SRT is about -10 to -13 dB (mean -11.3 dB, slope 15.3 %/dB). SRTs do not depend on presentation level above about 60 dB SPL. — [DIN evaluation, computationalaudiology.com](https://computationalaudiology.com/evaluation-of-a-digits-in-noise-din-test-for-auditory-research-and-clinical-application/); [medRxiv 2024 DIN](https://medrxiv.org/content/10.1101/2024.06.12.24308842v1.full.pdf)
- Model-based SRT: FADE and SII individualized with 315 audiograms predicted SRTs at RMSE 5.6 and 6.8 dB, and SII failed on steep losses (22.6 dB). Reference-free ASR/DNN models are evaluated the same way, by RMSE between predicted and observed SRT. — [arXiv 2203.09148](https://arxiv.org/pdf/2203.09148)
- On the clinical value of speech tests for predicting real-world benefit: quiet booth scores do not reliably predict real-world aid benefit. One study found no link between aided or unaided QuickSIN and subjective benefit once age was controlled. — [AudiologyOnline, Beyond Speech Intelligibility](https://www.audiologyonline.com/articles/beyond-speech-intelligibility-expanding-clinician-29406)

### Inferences
- A simulated "HASPI-SRT": sweep SNR from about -10 to +20 dB in 2-3 dB steps with speech-shaped noise and babble, find where HASPI's predicted proportion correct crosses 0.5, and report aided-minus-unaided SRT in dB. It reads like a QuickSIN SNR-loss improvement, which judges will recognize. It costs about 10-15 HASPI calls per scenario, which is still seconds.
- A passive linear horn amplifies speech and noise equally in each band. At a fixed SNR it improves intelligibility mainly through audibility (it lifts bands above threshold). Unaided, a hearing-impaired listener's SRT in noise is partly audibility-limited at 50-65 dB SPL, so some SRT benefit is expected. At 80 dB SPL, or in loud babble, the benefit should shrink toward zero or go slightly negative from upward spread of masking. This is a physically honest result and worth showing, not hiding. (Inference from linear-system reasoning, not a sourced claim.)
- Do not claim that simulated SRTs equal QuickSIN or HINT scores. Call them model-predicted SRT shifts.

### Gaps
- I did not retrieve HINT or WIN normative values or procedures.
- I found no head-to-head paper comparing SII, STOI and HASPI SRT-prediction accuracy on one dataset.
- STOI is not hearing-loss-aware without modification. I did not research HL-aware STOI variants.

## 5. Aided audiogram / functional gain

### Takeaway
Functional gain (unaided minus aided sound-field threshold) is discouraged for modern aids because compression, noise reduction and expansion make threshold-level gain unrepresentative of gain at conversational levels. For linear aids, functional gain matches insertion gain on average. For a passive linear horn it is legitimate, and in simulation it equals REIG near threshold.

### Cited Findings
- For linear aids, early probe-tube work found functional gain on average similar to insertion gain. NAL reported the two as equivalent. — [Hearing Health Matters, Functional Gain Part II](https://hearinghealthmatters.org/waynesworld/2011/hearing-aid-verification-using-functional-gain-part-ii/); [AudiologyOnline, Denis Byrne at NAL](https://www.audiologyonline.com/articles/research-denis-byrne-at-nal-1200)
- With nonlinear aids, compression complicates functional gain and can make thresholds look better than they are. Raising gain to improve functional gain can reduce it, because the aid enters compression sooner. — [Auditdata, Functional gain vs REM](https://www.auditdata.com/insights/blog/functional-gain-testing-vs-real-ear-measurements-which-is-better-for-hearing-aid-verification/); [Hearing Health Matters](https://hearinghealthmatters.org/waynesworld/2011/hearing-aid-verification-using-functional-gain-part-ii/)
- The aided threshold predicts the audibility of soft sounds, but it should not be used to describe or predict performance at supra-threshold levels. Kuk & Ludvigsen (2003, Trends in Amplification) proposed an "optimal aided threshold" approach for nonlinear aids. — [Hearing Review, Re-examining the aided threshold](https://hearingreview.com/practice-building/practice-management/changing-with-the-times-re-examining-the-aided-threshold); [PMC4168920](https://pmc.ncbi.nlm.nih.gov/articles/PMC4168920)
- Aided performance is best measured with real-ear probe-microphone measurements. — [Hearing Health Matters](https://hearinghealthmatters.org/waynesworld/2011/hearing-aid-verification-using-functional-gain-part-ii/)

### Inferences
- For a passive horn, a simulated aided audiogram is just the audiogram minus REIG at each audiometric frequency. It is trivial to compute and easy for a lay judge to read ("your 2 kHz threshold moves from 50 to 35 dB HL"). It is defensible because the device is linear. Say so explicitly, since an audiologist judge may reflexively object to functional gain.
- Physical sound-field functional gain testing with a printed prototype is one of the few real-world validations a hackathon team could run with a laptop audiometer app. It is valid for this device class, unlike for modern aids. Its test-retest variability, typically about 5 dB, was not sourced here.

### Gaps
- I did not source the test-retest reliability of sound-field thresholds.

## 6. Auditory-nerve-model-based metrics (NSIM, Bruce/Sachs/Young lineage)

### Takeaway
AN-model metrics are an established research line for evaluating and fitting hearing aids in silico, especially Bruce, Sachs, Young and Zilany at Johns Hopkins and McMaster, and Hines & Harte's NSIM. They are not a clinical or industry standard, they are much slower than HASPI, and they lack large listener validation sets. They are best presented as a secondary, mechanistic view (neurograms and hair-cell damage), not as the headline score.

### Cited Findings
- Bruce, Sachs & Young (2003), JASA 113:369-388, "An auditory-periphery model of the effects of acoustic trauma on auditory nerve responses." It aims to reproduce the damaged AN's tonotopic representation and predicts the effects of frequency-shaping amplification on AN responses, "indicating its potential suitability for more rapid development and testing of hearing aid schemes." — [McMaster experts record](https://experts.mcmaster.ca/scholarly-works/61874); [Bruce CHR 2006](https://www.ece.mcmaster.ca/~ibruce/papers/Bruce_CHR_2006.pdf)
- Sachs et al. (2002), "Biological Basis of Hearing-Aid Design" (Annals of Biomedical Engineering), models noise-induced OHC damage by scaling the model's feedback signal and uses the model to test a hearing-aid processing strategy. — [Sachs ABME 2002](https://www.ece.mcmaster.ca/~ibruce/papers/Sachs_ABME_2002.pdf); [McMaster record](https://experts.mcmaster.ca/scholarly-works/61875)
- Follow-up model-based fitting work by Bruce et al. investigated single-band gain adjustments to linear prescriptions (NAL-R, DSL) using model AN fiber responses to TIMIT sentences. The optimal adjustments depended on whether the error metric included spike-timing information. — [McMaster expert record / 2008 gain-prescription paper](https://experts.mcmaster.ca/display/publication61868); [Zilany IHCON 2004](https://www.ece.mcmaster.ca/~ibruce/papers/zilany_IHCON2004.pdf)
- NSIM (Hines & Harte) is a simplified SSIM applied to neurograms. It compares impaired AN model output with a normal-hearing reference and was used to predict speech intelligibility (Speech Communication, 2012). It was applied to the "chimaera" hearing aid algorithm to check whether intelligibility improves while fine timing cues are preserved. It ranked neurograms better than relative MSE. — [TCD TARA record](https://www.tara.tcd.ie/items/30dafbce-9760-4d5a-b1c9-0fe0114aea74); [ISAAR 2011 proceedings](https://proceedings.isaar.eu/index.php/isaarproc/article/download/2011-40/156); [Interspeech 2012, Hines](https://www.isca-archive.org/interspeech_2012/hines12_interspeech.html)
- NSIM is still in use in 2025 for modeling hearing loss plus cochlear neural degeneration (cochlear synaptopathy). — [arXiv 2506.12705](https://arxiv.org/html/2506.12705v1)

### Inferences
- Strengths over HASPI: physiologically grounded, with separate cohc/cihc parameters, so OHC-vs-IHC loss can be shown, not just the audiogram. Spike-timing (TFS) neurograms capture effects that HASPI's envelope-only back-end ignores. Neurogram images also make a compelling demo visual.
- Weaknesses: far slower. A Zilany/Bruce model at 100 kHz sampling across about 30 CFs and several fiber types is seconds to minutes per clip, not milliseconds. It is also stochastic (spike generation), lacks large listener-score validation comparable to HASPI's fits, and is not recognized by clinicians as an outcome measure. Mapping an audiogram to cohc/cihc is itself a modeling assumption; the common convention is about 2/3 OHC and 1/3 IHC loss (not verified this session).
- Recommended framing: HASPI and SII are the scores; the AN model is the explanation. Show ENV/TFS neurograms of unaided vs aided for one clip and report NSIM as a corroborating metric. Do not run it in the inner optimization loop.

### Gaps
- I could not fetch the Hines & Harte 2012 full text (403). The exact NSIM formula, window sizes and correlation with listener scores are not recorded here. From background knowledge (not verified this session): Speech Communication 54(2):306-320, using the Zilany et al. 2009 AN model with ENV and TFS neurograms.
- I did not obtain runtime benchmarks for the `cochlea` or `brucezilany` Python packages.

## 7. Self-report outcome measures (APHAB, SSQ, COSI)

### Takeaway
APHAB, SSQ and COSI are the standard patient-reported outcomes. They cannot be simulated, but their situation categories are a defensible, citable way to define and weight the simulated listening scenes. COSI is especially useful because it is patient-chosen: up to 5 priority situations.

### Cited Findings
- APHAB: 24 items in four subscales: Ease of Communication, Reverberation, Background Noise, Aversiveness. It is completed for both unaided and aided listening, so benefit can be read directly. — [AudiologyOnline, Self-report assessment overview](https://www.audiologyonline.com/articles/self-report-assessmenthearing-aid-931); [PMC9952610](https://pmc.ncbi.nlm.nih.gov/articles/PMC9952610)
- SSQ: three subscales, Speech, Spatial and Qualities of Hearing, covering complex everyday listening. Sources disagree on the item count (49 vs 50). — [PMC9952610](https://pmc.ncbi.nlm.nih.gov/articles/PMC9952610); [J Am Acad Audiol 2018;29(1):25-34](https://www.thieme-connect.de/products/ejournals/html/10.3766/jaaa.16102)
- COSI: the patient picks up to 5 listening situations from 16 standard categories and rates the benefit obtained. — [open-exam-prep outcome measures](https://open-exam-prep.com/study-guides/ihs-ile/continuing-care-rehabilitation/outcome-measures); [AudiologyOnline overview](https://www.audiologyonline.com/articles/self-report-assessmenthearing-aid-931)
- Older listeners report poorer SSQ ability and more APHAB difficulty, even with self-reported normal hearing (n = 254). — [PMC9952610](https://pmc.ncbi.nlm.nih.gov/articles/PMC9952610)

### Inferences
- Map pipeline scenes to APHAB subscales:
  - Quiet speech at 50 or 65 dB SPL maps to Ease of Communication.
  - Babble at +5 dB SNR maps to Background Noise.
  - A reverberant condition, if added, maps to Reverberation.
  - 80 dB SPL loud speech or noise maps to Aversiveness. Relevant because a passive horn cannot limit output; check that horn resonance does not push loud sounds toward discomfort.
- At intake, have the user rank COSI-style priorities (for example "conversation with 1-2 people in quiet", "group in noise", "TV") and use the ranks as weights on per-scene HASPI deltas. This turns a generic score into a patient-specific objective and is easy to justify to judges.

### Gaps
- I did not retrieve the 16 COSI categories verbatim (Dillon et al. 1997, J Am Acad Audiol). Get them from the original paper before using them in the UI.

## 8. Synthesis: compute cost and judge recognizability for a passive horn

### Takeaway
A defensible simulated suite, in priority order:
1. REIG vs NAL-R target (RMS error, % within ±5 dB).
2. Aided SII at 50/65/80 dB SPL in quiet and at +5 dB SNR.
3. HASPI v2 delta, aided minus unaided, per scene, plus an optional HASPI-derived SRT shift.
4. Simulated aided audiogram, for lay readability.
5. HASQI v2 as a sound-quality guardrail.
6. AN-model neurograms and NSIM as mechanistic illustration.

Items 1-5 each take well under a few seconds per scenario. Item 6 does not.

### Cited Findings
- REM against targets with a ±5 dB tolerance is standard clinical verification. — [AudiologyOnline QuickTakes Vol 6](https://www.audiologyonline.com/articles/research-quicktakes-volume-6-pt-28708-28708)
- SII is an ANSI standard, and aided SII is used clinically. — [ANSI Blog](https://blog.ansi.org/speech-intelligibility-index); [E3 Diagnostics](https://e3diagnostics.com/blog/speech-intelligibility-index)
- HASPI is the official baseline in the Clarity hearing-aid challenges, with known accuracy limits (CPC2 RMSE 28.7, r = 0.70). — [Clarity CPC2 results](https://claritychallenge.org/docs/cpc2/cpc2_results)
- Functional gain is valid for linear aids. — [Hearing Health Matters](https://hearinghealthmatters.org/waynesworld/2011/hearing-aid-verification-using-functional-gain-part-ii/)

### Inferences
- Recognizability to judges:
  - An audiologist will recognize REIG-to-target, SII and QuickSIN-style SNR loss.
  - A speech or ML engineer will recognize HASPI, STOI and Clarity.
  - A neuroscience judge will recognize the Bruce/Zilany AN model.
  - Leading with REIG plus SII plus HASPI covers all three groups.
- Cost estimates (not benchmarked):
  - REIG and aided audiogram are free once the acoustic model has produced the curve.
  - SII takes microseconds to milliseconds.
  - HASPI and HASQI take about a second per clip, so a full 3-level × 2-condition × N-clip grid is tens of seconds.
  - A HASPI SRT sweep takes about 10× that.
  - AN-model neurograms take tens of seconds or more per clip.
- Honesty points to state in the demo:
  1. The horn is linear, so it cannot meet NAL-NL2's level-dependent targets. NAL-R is the right target.
  2. HASPI ranks designs; it does not predict a given patient's absolute score.
  3. A linear device gives little SNR benefit in noise at high levels.
  4. Insertion gain must account for the open-ear resonance the device removes.
  5. No metric here replaces probe-mic REM on a printed prototype.

### Gaps
- No runtimes were measured for this hardware or packages.
- No published precedent was found for model-based fitting of a passive, non-electronic hearing device. That is novel, so judges have no prior benchmark to compare against.
