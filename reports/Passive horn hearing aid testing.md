# Score the horn against the open ear

The most important rule for this project is that every simulated benefit has to be scored as **insertion gain**. That means eardrum sound pressure with the horn in place minus eardrum sound pressure of the same open ear, from the same direction. The open concha and ear canal already give about **10-20 dB of natural gain peaking near 2.7-3 kHz**, and that is the same band a concha-length horn works in. Score the horn against a bare tube or a free-field microphone and the benefit comes out roughly 10-20 dB too high. Measured against the open ear, a realistic passive in-concha horn nets **a few dB, perhaps up to 10 dB, across roughly 1.5-4 kHz**. That is enough for adults with mild, high-frequency-sloping loss. It is not enough for "mild-to-moderate" loss, which needs roughly 25-30 dB.

The simulated tests worth running are the ones clinicians and hearing-aid researchers already use:

- **Primary score:** insertion gain checked against a *linear* NAL-R target, reported as RMS error and the share of frequencies within ±5 dB.
- **Intelligibility:** aided Speech Intelligibility Index (SII), plus HASPI v2 scores reported as aided minus unaided, with a model-predicted speech-reception-threshold (SRT) shift.
- **Supporting views:** a simulated aided audiogram for lay readers, HASQI as a sound-quality guardrail, and auditory-nerve neurograms as an illustration only.

Speaker angle matters for how much sound reaches the ear: head shadow moves high-frequency level by up to about 15 dB. It barely changes what a nearly omnidirectional, concha-sized horn adds. So model angle as a cheap level filter applied the same way to the aided and unaided conditions, over a few angles that each mean something. It does not need to be a 3D-simulated scene dimension. The 100-scene set also needs background noise, its weights should come from patient-ranked listening situations, and the canal-shape samples should be treated as uncertainty to design against rather than averaged away.

## Clinics verify fits by insertion gain within 5 dB of a target

The clinical gold standard for checking a hearing-aid fit is real-ear measurement. A probe microphone at the eardrum records the open ear (REUR) and then the aided ear (REAR). Their difference is the insertion gain (REIG), the benefit the device adds over the ear's own acoustics ([Hearing Review](https://hearingreview.com/practice-building/practice-management/integrated-rem-real-ear-measurement-from-a-hearing-aid)). Audiologists adjust until the output is **within 5 dB of the prescriptive target at each frequency**. Cox and Alexander found that differences between prescriptions survive when the RMS error to target is 5 dB or less ([AudiologyOnline](https://www.audiologyonline.com/articles/research-quicktakes-volume-6-pt-28708-28708)).

Matching targets is hard even for electronic aids:

- More than 84% of pediatric fittings for mild-to-moderate loss landed within 5 dB at all test levels ([J Am Acad Audiol 2020](https://www.thieme-connect.de/products/ejournals/html/10.3766/jaaa.19057)).
- One manufacturer poster reports 83.2% of ears within ±5 dB at 250-3000 Hz, falling to **62.0% at 4-6 kHz** ([Starkey/NAL poster](https://cdn.mediavalet.com/usil/starkeyhearingtech/bx7nNMoJXkeGdF5clHzMsw/bdNwzROR2k2SXnbpLgaxYA/Original/JDVAC%202025%20ESTAT%20and%20NAL%20REAR%20Poster.pdf)).
- Manufacturers' own "NAL-NL2" first fits miss real-ear targets significantly ([Hearing Review 2015](https://hearingreview.com/2015/02/manufacturers-nal-nl2-fittings-fail-real-ear-verification)). In 55% of them, the fit was 10 dB or more below target at one or more frequencies ([Hearing Review 2015](https://hearingreview.com/hearing-products/testing-equipment/manufacturers-nal-nl2-fittings-fail-real-ear-verification)).

A judge who knows audiology will recognize "RMS error to target, percent within ±5 dB" right away. This should be the headline fitting metric.

The choice of target matters because a passive horn is **linear**: its gain is the same at 50, 65 and 80 dB SPL. NAL-NL2 and DSL v5 set different gains for different input levels, so a fixed filter can match them at one input level at most. The natural target for a passive device is therefore NAL-R, the linear NAL prescription. It also keeps the scoring consistent: **HASPI v2 was trained on hearing-impaired listeners whose speech was amplified with NAL-R** ([Kates 2023, PMC10257526](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)).

Linearity also brings back a test that modern clinics have dropped. Functional gain (unaided minus aided sound-field threshold) is discouraged for compressive aids, because compression makes threshold-level gain misleading ([Auditdata](https://www.auditdata.com/insights/blog/functional-gain-testing-vs-real-ear-measurements-which-is-better-for-hearing-aid-verification/)). **For linear aids, functional gain matches insertion gain on average** ([Hearing Health Matters](https://hearinghealthmatters.org/waynesworld/2011/hearing-aid-verification-using-functional-gain-part-ii/)). A simulated aided audiogram, the audiogram minus REIG at each frequency, is therefore valid for this device. Lay judges can read it at a glance ("your 2 kHz threshold moves from 50 to 35 dB HL"). Say explicitly why it is valid here, because an audiologist will expect the usual objection to functional gain.

Patient questionnaires cannot be simulated, but they give the scene set a citable structure:

- APHAB has subscales for Ease of Communication, Reverberation, Background Noise and Aversiveness ([AudiologyOnline](https://www.audiologyonline.com/articles/self-report-assessmenthearing-aid-931)).
- SSQ covers speech, spatial hearing and sound quality ([PMC9952610](https://pmc.ncbi.nlm.nih.gov/articles/PMC9952610)).
- COSI has each patient pick **up to five priority situations from 16 standard categories** ([AudiologyOnline](https://www.audiologyonline.com/articles/self-report-assessmenthearing-aid-931)).

Mapping simulated scenes onto these categories turns a generic score into a patient-specific objective that can be defended.

## SII and HASPI can rank designs but cannot predict one patient's score

The **Speech Intelligibility Index (ANSI S3.5-1997)** is the cheapest metric with a standard behind it. It sums band importance times band audibility, computed from the speech spectrum, the noise spectrum and the hearing thresholds ([ANSI](https://blog.ansi.org/speech-intelligibility-index)). Open implementations exist, including an optional hearing-loss desensitization factor ([R SII package](https://rdrr.io/cran/SII/man/sii.html)). For a linear device, aided SII follows directly from the insertion-gain curve, so it costs nearly nothing inside an optimizer. Its evidence is useful: the *change* in SII predicted self-reported APHAB and HHIE-A benefit once unaided SII was controlled for ([Kim et al. 2016](https://haar.lab.uiowa.edu/sites/haar.lab.uiowa.edu/files/2022-08/Kim%20et%20al%20AAS%202016.pdf)).

SII measures audibility, not understanding. Audibility alone fails to explain recognition for many hearing-impaired listeners, especially severe losses at high sensation levels ([Ching et al. 1998](https://researchers.mq.edu.au/en/publications/speech-recognition-of-hearing-impaired-listeners-predictions-from/)). Added high-frequency audibility helps little once loss passes about 55 dB HL ([PMC6688860](https://pmc.ncbi.nlm.nih.gov/articles/PMC6688860)). Across 315 audiograms, SII predicted SRTs with **6.8 dB RMS error overall but 22.6 dB for steep losses** ([arXiv 2203.09148](https://arxiv.org/pdf/2203.09148)). Turn on the desensitization factor and expect SII to over-credit high-frequency gain.

**HASPI v2** is the stronger second-stage score, and a passive linear horn sits unusually close to its training conditions. HASPI runs clean and processed speech through an auditory model that accounts for hearing loss. It then maps how faithfully the speech envelope is preserved to the proportion of sentences correct. On its own training data it reaches **r = 0.956-0.973** for noise, distortion and reverberation ([PMC10257526](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)). The catch is generalization: on unseen hearing-aid listener data in the Clarity CPC2 challenge, the HASPI baseline scored **RMS error 28.7 percentage points, r = 0.70** ([Clarity CPC2](https://claritychallenge.org/docs/cpc2/cpc2_results)).

So HASPI ranks horn designs credibly but cannot tell a patient what percentage of words they will understand. Three practical details matter:

- The score's ceiling in quiet falls with hearing loss, from 0.946 to 0.636 across standard audiograms ([PMC10257526](https://pmc.ncbi.nlm.nih.gov/articles/PMC10257526)). Raw scores are therefore not comparable across patients.
- The pyclarity implementation calibrates presentation level through a `level1` parameter that defaults to 65 dB SPL ([clarity source](https://github.com/claritychallenge/clarity/blob/main/clarity/evaluator/hasqi/hasqi.py)). If it is set wrong, audibility changes silently.
- The ear model uses random noise ([clarity PR #364](https://github-redirect.dependabot.com/claritychallenge/clarity/pull/364)). Seed it, average over noise samples and clips, and treat small differences as ties.

Clinical speech-in-noise tests report SNR loss. QuickSIN classifies **0-3 dB as normal, 3-7 mild, 7-15 moderate, and over 15 dB severe** ([HearingTracker](https://www.hearingtracker.com/expert_answers/1298)). A simulated version sweeps SNR, finds where predicted intelligibility crosses 50%, and reports the aided-minus-unaided shift. Model-based SRT prediction is established practice, with roughly 5.6-6.8 dB RMS error across audiograms ([arXiv 2203.09148](https://arxiv.org/pdf/2203.09148)). Call the result a *model-predicted SRT shift*, never a QuickSIN score. Even the real clinical tests predict real-world benefit poorly ([AudiologyOnline](https://www.audiologyonline.com/articles/beyond-speech-intelligibility-expanding-clinician-29406)).

The physics sets an expectation the demo should show openly. A linear horn amplifies speech and noise equally in every band, so it improves understanding in noise only by making speech audible. That benefit should shrink toward zero in loud babble at 80 dB SPL.

Auditory-nerve models, such as the Bruce/Zilany models and Hines and Harte's neurogram similarity measure (NSIM), have a real research history in hearing-aid evaluation ([Bruce et al.](https://experts.mcmaster.ca/scholarly-works/61874); [Interspeech 2012](https://www.isca-archive.org/interspeech_2012/hines12_interspeech.html)). They are slow, they produce random spike trains, and clinicians do not recognize them as outcome measures. Use them to explain the result with an unaided-versus-aided neurogram for one clip, not to score designs.

| Metric | What it answers | Cost per scene | Who recognizes it | Role |
|---|---|---|---|---|
| REIG vs NAL-R (RMS error, % within ±5 dB) | Does the horn deliver the prescribed gain over the open ear? | Free once the acoustic curve exists | Audiologists | Headline fit score |
| Aided SII at 50/65/80 dB SPL, quiet and +5 dB SNR | How much speech is audible? | Microseconds | Audiologists | Fast inner-loop objective |
| HASPI v2 delta, plus a model-predicted SRT shift | Does predicted intelligibility improve? | About a second per clip, roughly 10x for an SRT sweep (not benchmarked) | Speech and ML engineers (Clarity) | Ranking confirmation |
| Simulated aided audiogram | Which thresholds move, in plain terms? | Free | Everyone | Lay readout |
| HASQI v2 | Does a sharp resonance make it sound tinny or honky? | About a second per clip | Speech engineers | Guardrail against overfitting |
| AN-model neurograms / NSIM | Mechanism | Tens of seconds or more per clip | Neuroscientists | Illustration only |

## Head shadow moves level up to 15 dB, while horn directivity adds about 1 dB

Speaker angle is important, but mostly through head shadow, which exists with or without the horn. Shaw's 1974 synthesis of 12 studies tabulates the free-field-to-eardrum transformation at **15-degree azimuth steps from 0.2 to 12 kHz** ([PubMed 4443484](https://pubmed.ncbi.nlm.nih.gov/4443484/)). A companion paper gives it in numerical form, ready to use as a lookup table ([Scilit](https://scilit.com/publications/282faeae31950eea1af13ea3d0bb0556)). In-ear measurements show spectral changes of **up to about 15 dB relative to the front** for sources at 45 and 120 degrees ([Jensen et al. 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)). The roughly 10 dB spatial advantage for speech in noise comes mostly from head shadow; binaural timing adds only about 2-3 dB ([Shinn-Cunningham et al. 2001](https://www.cmu.edu/dietrich/psychology/shinn/publications/pdfs/2001/2001jasa_shinn.pdf)).

For a single-ear device, the relevant quantity is how level changes at the aided ear as the talker moves. A talker on the aided side gains a little level; a talker on the far side loses up to about 10-15 dB at 2-8 kHz, and the horn cannot recover it.

The horn's own directional contribution is small. On a real head, even directional microphones reach only about **2.3-3.5 dB directivity index for first-order patterns**, roughly 3 dB below their free-field values ([Dittberner and Bentler 2003](https://hearingreview.com/practice-building/practice-management/interpreting-the-directivity-index-di)). Canal-located omnidirectional microphones show about -0.5 to 0.2 dB of speech-weighted directivity (vendor figures, [US 6704423](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6704423)).

Moving the inlet into the concha mainly helps localization. It reduces front-back error by a mean of 22 degrees, but its speech-in-noise effect is only about **1 dB** ([Jensen et al. 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)). Aperture physics agrees (our calculation, standard ka > 1 criterion): a 2 cm horn mouth only starts to become directional around 5.5 kHz. Directivity at 1-2 kHz would need an ear-trumpet-scale mouth of 10-20 cm. No measured polar data for ear trumpets or concha horns turned up, so the claim that horn directivity is second-order rests on physics and on these microphone-location comparisons.

Two angle cases still deserve their own scenes because they expose real failure modes:

- **Talker on the far side.** Here the horn cannot help at all. With hearing loss, spatial release from masking (the benefit of separating talker and noise) is already small: 6.1 dB for younger normal-hearing listeners and **2.7 dB for older hearing-impaired listeners** ([Dubno et al. 2002](https://pubs.asha.org/doi/10.1044/1092-4388(2002/104))). One model simulation found none at all for a hearing-impaired configuration ([arXiv 2007.05378](https://arxiv.org/pdf/2007.05378)).
- **Noise on the aided side.** Bilateral aids preserve more of this spatial benefit than unilateral aids ([PMC5392088](https://pmc.ncbi.nlm.nih.gov/articles/PMC5392088)). A one-ear horn with noise on its side and the talker opposite boosts the noise relative to the talker. A credible scene set has to show this case.

The cheapest credible model is to separate angle from horn optimization. Apply an angle-dependent filter at the ear entrance, using either Shaw's table or the Brown and Duda spherical-head model ([Brown and Duda 1998](https://escholarship.org/content/qt0cr9d23p/qt0cr9d23p_noSplash_c6f0ae8be6c4003ba4f479c6ef3d369b.pdf)), and run the same angle filter for aided and unaided conditions. Full 3D boundary-element simulation of a head per angle is out of reach in a weekend: older audible-range head-response runs took **9-28 hours per frequency** ([arXiv 1606.00278](https://ar5iv.arxiv.org/html/1606.00278)).

The one exception is a horn whose mouth is larger than about 4 cm or sticks out beyond the concha. Its own directivity starts to matter above about 3 kHz, and the final design deserves a coarse 3D check at a few angles. One more point follows: because angle mostly acts as a frequency-dependent level offset, it partly overlaps the level axis. A far-side talker at 65 dB SPL looks a lot like a quieter front talker in the high frequencies.

## Concha-length horns net a few dB in the band the ear already boosts

The "13.4 dB" figure from patent US11743635B2 is the ideal lossless limit for its 22.2:1 area ratio (10·log10 22.2 = 13.46 dB). The patent gives no test setup. That gain also relies on a **186.8 mm** acoustic path with a 459 Hz cutoff, and the independent claims cover a horn feeding a **MEMS microphone port**, not an ear canal ([Google Patents](https://patents.google.com/patent/US11743635B2/en)). Chasin gives the same rule for hearing-aid tubing: maximum gain is 10·log(area ratio), so a 2→4 mm flare gives 6 dB, and only above a cutoff set by length ([Hearing Health Matters](https://hearinghealthmatters.org/hearthemusic/2014/acoustics-hearing-aids-tubes-flare-part-3/)). The table below applies the standard exponential-horn cutoff formula (our calculation, 22:1 flare) to lengths that fit in or near a concha.

| Horn path length | Approximate lower cutoff |
|---|---|
| 60 mm | 1.4 kHz |
| 40 mm | 2.1 kHz |
| 30 mm | 2.8 kHz |
| 20 mm | 4.2 kHz |

A concha-sized horn therefore works at 2-4 kHz, right where the open ear is already strongest. Adult open-ear gain peaks at about **2.7-3 kHz with roughly 10-20 dB** of natural gain ([Interacoustics](https://interacoustics.com/academy/hearing-aid-fitting-training/rem/what-should-an-adult-reug-look-like)). The concha resonance adds **5-8 dB near 4-5 kHz** ([Hearing Review, Chasin 2013](https://hearingreview.com/practice-building/practice-management/continuing-education/the-acoustics-of-hearing-aids-part-2-a-closer-look-at-boyle-s-law)).

Devices that block the ear remove that natural gain. Sealed earmolds have attenuated by as much as 35 dB in some people, while truly open fits change the response by only about 3 dB ([Hearing Review, Wang 2004](https://hearingreview.com/practice-building/practice-management/big-assumptions-understanding-insertion-loss-in-hearing-aids)). The relevant area ratio for an ear device is the collector opening, bounded by concha size, over the canal entrance, which averages 97 mm² in CT data ([Smith College](https://scholarworks.smith.edu/egr_facpubs/143)). That probably caps the ideal gain in the single digits of dB.

Printed channels lose more than smooth-tube models predict. Layer roughness of 25-100 µm is about the same size as the 40-140 µm acoustic boundary layer (our calculation), which damps the resonant peaks a lossless simulation will show. Treat any simulated throat gain above about 10 dB as suspect. Historical figures confirm that only large collectors reach double digits: hearing bells at **15-20 dB at 2.5 kHz** ([AfH Lübeck museum](https://www.afh-luebeck.de/en/akademie/hoergeraete-museum/)), a cupped hand at about 12 dB at 1 kHz ([Hearing Aid Museum](https://www.hearingaidmuseum.com/gallery/General_Info/GenInfoNonElect/info/generalinfo-eartrumpets.htm)), and a headband trumpet at up to about 10 dB over a limited band ([Becker Library](https://becker.wustl.edu/?p=17889)).

Occlusion and venting create a real dilemma for a concha device. A seal near the canal entrance is the worst case. Shallow seals raise the wearer's own voice at low frequencies by **20-30 dB at 250 Hz**, while deep bony-canal seals average -3.6 dB. A vent of at least 2 mm is the usual relief ([Hearing Review, Staab 2003](https://hearingreview.com/hearing-products/accessories/earmolds/solving-the-occlusion-effect)). A 3 mm vent also adds its own resonance of up to 6-8 dB around 1.1-1.5 kHz ([AudiologyOnline](https://www.audiologyonline.com/ask-the-experts/occlusion-effect-567)). The vent leaks horn output below about 1 kHz, but a passive horn has no amplifier loop and so cannot squeal. The vent can be as large as the gain target allows, a real advantage over electronic aids.

Do not borrow the hearing-aid figures for gain from a smaller residual canal volume. Chasin's "3 dB per halving" assumes a sealed loudspeaker in the canal, and he puts the net low-frequency benefit at only about 1 dB ([Hearing Review](https://hearingreview.com/practice-building/practice-management/continuing-education/the-acoustics-of-hearing-aids-part-2-a-closer-look-at-boyle-s-law)). Model the canal with an eardrum load instead. Air-conduction acoustic models also cannot capture own-voice occlusion, so state that it is not simulated.

These limits define the realistic users. NAL's data put preferred gain at about 0.46 times threshold ([AudiologyOnline](https://www.audiologyonline.com/articles/research-denis-byrne-at-nal-1200)), which means about **14-15 dB at 30 dB HL, 18-20 dB at 40 dB HL and 25-28 dB at 55 dB HL** (our calculation). A real 5-10 dB net gain in a 2-4 kHz band fits adults with mild (about 25-40 dB HL), high-frequency-sloping loss and good low-frequency hearing, who can tolerate a big vent. It does not cover moderate loss.

Do not use the WHO's **430 million** people needing rehabilitation as the market. That figure counts loss greater than 35 dB in the better ear ([WHO](https://www.who.int/news-room/fact-sheets/detail/deafness-and-hearing-loss)), which excludes most of the mild-loss users this device could serve.

On printing, earmold-grade resins such as Formlabs BioMed Clear carry ISO 10993 data only for the validated printer, wash and cure workflow ([Formlabs](https://formlabs.com/materials/medical)). Long sub-2 mm internal channels are hard to wash and trap uncured resin. Prefer flushable channels of 1.5-2 mm or more, and avoid FDM printing for anything worn in the ear.

## FDA's definition depends on the marketing claim, not the battery

Federal regulation defines a hearing aid as **"any wearable device designed for, offered for the purpose of, or represented as aiding persons with or compensating for, impaired hearing"**, with no electronics requirement ([21 CFR 800.30](https://www.law.cornell.edu/cfr/text/21/800.30)). An air-conduction hearing aid is Class I and exempt from premarket notification, subject to general controls ([21 CFR 874.3300](https://www.law.cornell.edu/cfr/text/21/874.3300)). FDA's companion guidance holds that products sold to accentuate sound for people without hearing loss (PSAPs) become hearing aids once they make explicit or implicit hearing-loss claims ([MedTech Dive](https://www.medtechdive.com/news/fda-final-rule-OTC-hearing-aids/629769/)).

The over-the-counter performance rules were written for electronics. A passive horn trivially meets the **111 dB SPL output cap**, the 15 ms latency limit and the distortion limit. The requirement for bandwidth from 250 Hz to 5 kHz ([21 CFR 800.30](https://www.law.cornell.edu/cfr/text/21/800.30)) could be a real obstacle for a 2-4 kHz horn, and how FDA would apply it to a non-electronic device is unknown. The nearest commercial precedent, Amano Labs' $19.99 3D-printed "mechanically amplified" device for "mild to moderate hearing loss", has published **no gain figure, frequency response or regulatory status** ([Homegrown](https://homegrown.co.in/homegrown-voices/amano-labs-wants-to-make-hearing-aids-more-accessible-one-20-device-at-a-time)). That leaves an opening for a team that publishes data.

Validation sets the second ceiling on claims. No published study was found that checks insertion gain predicted by finite-element or boundary-element simulation of a patient's ear mesh against probe-microphone measurement. The model's accuracy, especially above 4 kHz, is unknown. KEMAR with anthropometric pinnae matches a median human ear up to about 8 kHz ([Acta Acustica 2021](https://acta-acustica.edpsciences.org/articles/aacus/full_html/2021/01/aacus200022/aacus200022.html)). Individual open-ear response varies enough that a larger-than-average REUR reads as insertion loss ([Hearing Review](https://hearingreview.com/practice-building/practice-management/big-assumptions-understanding-insertion-loss-in-hearing-aids)).

A weekend bench check is still possible. Print a rigid canal simulator (about 7.5 mm by 25-30 mm) with a small measurement microphone, optionally with the patient's printed pinna. Play pink noise or a sweep from a fixed speaker and record three conditions: open, horn in place, and a solid plug of the same outer shape. Horn minus open is insertion gain on the simulator; plug minus open is insertion loss. Every number is relative, so the microphone needs no calibration. A rigid tube lacks eardrum impedance, though, so it will exaggerate resonance peaks. It also cannot show own-voice occlusion or speech benefit, which need human testing and an ethics (IRB) review.

## Recommended test suite, angle plan, scene weights and claims

### Optimize on cheap scores, then confirm finalists with HASPI

Use REIG-to-NAL-R error plus weighted aided SII as the fast inner-loop objective. Apply hard constraints for:

- no band between 0.5 and 4 kHz with REIG below about -3 dB (the open-fit insertion-loss benchmark);
- simulated throat gain above about 10 dB, which gets flagged as a likely lossless-model artifact;
- a HASQI score no worse than unaided in the 80 dB scene, which guards the Aversiveness category.

Rescore the top few designs on the full scene set with HASPI v2, seeded and averaged, and add a model-predicted SRT shift for the front-noise scene.

The two-ear-model setup supports one more useful number, **gap closed = (aided − unaided) / (healthy − unaided)**. This normalizes away the fact that HASPI's ceiling falls with hearing loss, so results can be compared across patients. The unaided condition must include the simulated open-ear resonance from the same mesh and the same angle filter.

### Restructure the 100 scenes around level, noise and canal uncertainty

The current grid has no background noise. Quiet-only scenes overstate what a linear device does, because they test only audibility. Angle should enter as a pre-computed head-shadow filter, not as a 3D simulation. The table below gives 8 conditions; 8 conditions × 3 clips (mixing male and female talkers) × 4 canal samples = 96 scenes. The weights are default starting points chosen by reasoning, not taken from evidence. Replace them with the patient's own COSI-style rankings at intake.

| # | Scene | APHAB/COSI mapping | Default weight | Purpose |
|---|---|---|---|---|
| 1 | Quiet, talker 0°, 50 dB SPL | Ease of Communication (soft speech) | 0.15 | Audibility of soft speech |
| 2 | Quiet, talker 0°, 65 dB SPL | Ease of Communication | 0.25 | Design point for a linear device |
| 3 | Quiet, talker 0°, 80 dB SPL | Aversiveness | 0.10 | Loudness and quality guardrail |
| 4 | Babble +5 dB SNR, both at 0°, 65 dB SPL | Background Noise | 0.20 | Shows small benefit in noise |
| 5 | Talker 0°, babble at aided-side 90°, +5 dB SNR | Background Noise | 0.10 | One-ear stress case |
| 6 | Reverberant room, talker 0°, 65 dB SPL (if room responses available) | Reverberation | 0.10 | Ringing and smearing |
| 7 | Quiet, talker at aided-side 90°, 65 dB SPL | Spatial | 0.05 | Best case |
| 8 | Quiet, talker at far-side 270°, 65 dB SPL | Spatial | 0.05, or 0 in the objective and report only | Honest worst case the horn cannot fix |

Average across clips. Across canal samples, optimize a robust statistic such as the mean minus one standard deviation, or the worst quartile. A design that wins on only one canal shape is not personalized; it is fragile. Run 180° and a 15° sweep only as an after-the-fact chart for the demo. Add 3D angle simulation only if the chosen horn mouth is larger than about 4 cm or protrudes from the concha.

### Claims for the pitch

| Make | Do not make |
|---|---|
| "Predicted +X dB insertion gain at Y-Z kHz over this patient's simulated open ear, across N canal samples." | "13.4 dB" or "10-20 dB amplification" quoted from the horn formula or the patent. |
| "Fit to a linear NAL-R target: X dB RMS error, Y% of frequencies within the clinical ±5 dB tolerance." | "Matches NAL-NL2." A linear device can match it at one level at most. |
| "Model-predicted intelligibility (HASPI v2) improves for soft and conversational speech; HASPI is used to rank designs." | "Patients will understand X% more words." HASPI's error on unseen hearing-aid data is about 29 points. |
| "Model-predicted SRT shift of X dB." | "Equivalent to a QuickSIN or HINT improvement." |
| "Benefit shrinks in loud noise; a passive linear device cannot improve the signal-to-noise ratio." | "Helps you hear in noisy restaurants" or "focuses on the person in front of you." Horn directivity is about 1 dB. |
| "Battery-free, zero latency, no feedback, linear (no compression artifacts)." | "Restores spatial hearing." It is one ear and has no binaural processing. |
| "Aimed at adults with mild, high-frequency-sloping loss." | "For mild-to-moderate hearing loss," "treats hearing loss," or "hearing aid," unless the team accepts FDA hearing-aid status. |
| "Research prototype, not evaluated by FDA." | "FDA-exempt" or "FDA-compliant." |
| "Printed in a resin with ISO 10993 test data." | "Biocompatible device." |
| "Bench A/B on a printed ear simulator: +X dB insertion gain" (only if measured). | "Clinically validated" or "validated against real-ear measurement." |
| "Hundreds of millions of people live with mild loss that goes unaided" (only with a sourced figure). | "Serves the WHO's 430 million." That figure counts loss greater than 35 dB. |

## Conclusion

The project's real novelty is not the horn, since passive collectors are centuries old. It is fitting a passive device to a prescription with the clinic's own verification method, inside a simulator. No published precedent for model-based fitting of a non-electronic hearing device turned up, so judges have nothing to compare it against, and that makes rigor the strongest signal the team can send. A pitch that shows the open-ear baseline subtracted, reports a modest, believable number of dB against a linear target, and openly shows the loud-noise and far-side-talker cases where the horn does nothing will read as engineering rather than marketing. The simulation also works as a screening tool: if a patient's audiogram needs more than about 10 dB, or gain below 1.5 kHz, the right output is "this device is not for you." Saying that out loud is more credible than any gain figure.

The open uncertainties determine the next step. Nobody has measured how closely a mesh-based acoustic simulation predicts real-ear insertion gain for a concha device. Losses from printed surfaces and the real geometry of a folded horn are also unquantified. A single bench comparison of open ear, horn and plug on a printed ear simulator would turn the project's central number from a prediction into a measurement, and it would be the first published data point of its kind for this device class.
