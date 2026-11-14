# Realism of a Passive 3D-Printed In-Ear (Concha) Acoustic Horn Hearing Device

Scope note: findings come from web sources fetched on 2026-11-14. Where a figure came only from a search-result summary and not a fetched page, the line is marked "(snippet, not fetched)". Calculations I did myself are in the Inferences sections and labeled as calculations. They use standard textbook formulas whose sources were not fetched in this pass.

## 1. Passive acoustic gain: horn physics, ear trumpets, modern passive devices. Is 10-20 dB realistic in the concha?

### Takeaway
The patent's "13.4 dB" is exactly the ideal lossless area-ratio limit, 10·log10(22.2) = 13.46 dB. It is a theoretical ceiling, and the patent describes no measurement. It also needs a 186.8 mm path to reach down to 459 Hz. A horn short enough to fit in a concha (about 20-40 mm) with the same 22:1 flare has a cutoff around 2-4 kHz. That puts its band on top of the ear's natural 2.7 kHz resonance, which an in-ear device partly removes. Measured historical figures exist only for large external devices: hearing bells at 15-20 dB at 2.5 kHz, and a cupped hand at about 12 dB at 1 kHz. I found no peer-reviewed measurement of any concha-sized passive amplifier.

### Cited Findings

**Patent US11743635B2 (Anderson; now assigned to Audarium LLC)**
- Throat is 1 mm² (a channel 1 mm × 1 mm). Mouth is 22.2 mm² (about 7.4 mm × 3 mm). The area ratio is about 22.2:1, and the disclosed range is 4:1 to 25:1 — [Google Patents US11743635B2](https://patents.google.com/patent/US11743635B2/en)
- The patent says the horn "can provide as much as 13.4 dB of amplification." The text gives no test setup and does not say whether this was measured or calculated — [Google Patents](https://patents.google.com/patent/US11743635B2/en)
- The FIG. 9 effective length is about 186.8 mm, with a cutoff of about 459 Hz and "efficient amplification" starting near 688 Hz. FIG. 1 states a minimum length of about 8.5 cm for a 1000 Hz cutoff. Another passage gives a minimum of 41.4 mm for 2000 Hz. The claimed length range is 40-250 mm — [Google Patents](https://patents.google.com/patent/US11743635B2/en)
- The patent covers a different application. Independent claims 1 and 15 recite a horn whose throat attaches to a **MEMS microphone package substrate** enclosing the mic port hole, made of silicone (cl. 1) or rubber (cl. 15). It does not claim a passive horn feeding the ear canal. The horn drives a tiny, nearly closed mic-port volume — [Google Patents](https://patents.google.com/patent/US11743635B2/en)
- The FIG. 1 flare law is exponential, A_x = A_t·e^(4πx/λ). Parabolic, conical, hyperbolic, tractrix and stepped shapes are also listed — [Google Patents](https://patents.google.com/patent/US11743635B2/en)

**Area-ratio rule of thumb (hearing-aid acoustics literature)**
- Marshall Chasin gives the maximum gain of flared tubing as 10·log(area ratio). Doubling the inner diameter (4× area) gives 6 dB, for example in a 2→4 mm Libby horn. The gain applies only above a cutoff set by tube length, F = v/2L: above 2266 Hz for a 75 mm BTE tube and above 2833 Hz for a 60 mm tube — [Hearing Health Matters, Chasin 2014](https://hearinghealthmatters.org/hearthemusic/2014/acoustics-hearing-aids-tubes-flare-part-3/)
- Flared hearing-aid tubing from 2 mm to 4 mm ID gives "up to 6 dB of 'free amplification'" — [Canadian Audiologist](https://canadianaudiologist.ca/the-limitations-and-the-benefits-of-a-flared-tubing/?output=pdf) (snippet, not fetched)
- A calculated (not measured) horn example gives about 6 dB for a 1"→2" flare and about 20 dB for a 1"→10" flare, with 15.5 dB at 6", 12 dB at 4" and 6 dB at 2" — [Hearing Health Matters](https://hearinghealthmatters.org/?p=23713) (snippet, not fetched). These figures equal 10·log10 of the area ratio. Reaching 20 dB needs a 100:1 area ratio.

**Historical ear trumpets and collectors**
- The Academy of Hearing Acoustics (Lübeck) hearing-aid museum says classic ear trumpets gave "amplification to max. 30 decibel" with "no amplification at around 1.600 Hz" (strongly frequency-dependent). Late-19th-century hearing bells gave "measured amplification 15 to 20 decibel at 2.5 kHz." The first in-ear hearing aids (patented 1923) were "almost ineffective as far as the amplification is concerned" — [AfH Lübeck hearing aid museum](https://www.afh-luebeck.de/en/akademie/hoergeraete-museum/). The page gives no measurement method or citation.
- "Cupping your hand behind your ear can give you a 12 dB boost in volume at 1,000 Hz … and somewhat less at 2,000 to 3,000 Hz." Ear trumpets were "most effective when used close up with the person speaking directly into the opening." Neither claim is cited — [Hearing Aid Museum](https://www.hearingaidmuseum.com/gallery/General_Info/GenInfoNonElect/info/generalinfo-eartrumpets.htm)
- A non-authoritative page claims ear trumpets gave 10-25 dB, mainly below 2 kHz, citing a reference that could not be checked. Treat this as low reliability — [moviecultists.com](https://moviecultists.com/do-ear-trumpets-work) (snippet, not fetched)
- Wikipedia states that a sound trumpet does not "amplify" sound; it collects and concentrates it — [Wikipedia: Ear trumpet](https://en.wikipedia.org/wiki/Ear_trumpet) (snippet, not fetched)

**Modern passive devices**
- Amano Labs sells a custom-fit, "mechanically amplified" device at $19.99 with no batteries, charging or app. It is fitted remotely from a photo of the ear, uses 3D-printed parts and is marketed for "mild to moderate hearing loss." It is in pre-order with more than 1,300 orders and estimated delivery in Q4 2026. The company says it worked with more than 10 audiologists and tested with over 50 patients. The article reports **no gain figure, frequency response, measurement data or regulatory status** — [Homegrown](https://homegrown.co.in/homegrown-voices/amano-labs-wants-to-make-hearing-aids-more-accessible-one-20-device-at-a-time)
- An anonymous commenter claims mechanical amplification "rolls off above 2-3 kHz." This is unverified — [stacker.news](https://stacker.news/items/1490252) (snippet, not fetched)
- EARCOUSTIC is described as a compact amplifier for mild-to-moderate loss with no electronics, batteries or wires. No measurements were found — [Hearing Health Matters](https://hearinghealthmatters.org/?p=41171) (snippet, not fetched)
- Cup-and-headband "non-electric hearing amplifiers" sold on marketplaces work like cupping the ears — [desertcart listing](https://www.desertcart.vn/products/58072376-non-electric-hearing-amplifier-works-like-cupping-your-ears-helps) (snippet, not fetched)

**Ear canal geometry (sets the load the horn must drive)**
- A CT study of 66 adult ears found a canal length of 31.4 ± 3.1 mm and an entrance area of 97 ± 24 mm². The area at the first bend is 53 ± 18 mm² (44 mm² in ages 18-30, 69 mm² in ages 61-90). The area at the tympanic annulus is 56 ± 8 mm² — [Smith College ScholarWorks, CT ear-canal geometry](https://scholarworks.smith.edu/egr_facpubs/143) (snippet, not fetched). The textbook figure is about 2.5 cm long and 0.6 cm in diameter.

### Inferences
- **The patent's 13.4 dB is a formula, not a measurement.** 10·log10(22.2) = 13.46 dB (calculation). The 459 Hz cutoff equals c/(4L) = 343/(4 × 0.1868 m) = 459.0 Hz (calculation). An exponential horn with the same 22.2:1 ratio over 186.8 mm gives f_c = m·c/(4π) ≈ 453 Hz (calculation). The project should cite it as "the ideal lossless area-ratio limit for a 22:1 horn," never as demonstrated gain.
- **Concha-length horns have high cutoffs.** For an exponential horn with a 22.2:1 area ratio, f_c = ln(22.2)·c/(4πL) (my calculation):
  - L = 60 mm: about 1.4 kHz
  - L = 40 mm: about 2.1 kHz
  - L = 30 mm: about 2.8 kHz
  - L = 20 mm: about 4.2 kHz

  Getting below 1 kHz needs a path of roughly 85 mm or more, which agrees with the patent's own 8.5 cm minimum for 1000 Hz. That path would have to be coiled or folded inside the concha. Folding adds length in narrow channels, and narrow channels add viscothermal loss.
- **The patent's geometry does not map onto an ear-canal load.** Its 1 mm² throat feeds a closed MEMS mic port. A device in the ear must deliver sound into a canal of about 44-97 mm² (CT data above). The patent's 22.2 mm² "mouth" is smaller than the canal itself. Ending a 1 mm² throat into a canal 40-100× larger is a constriction, not a transformer. For an ear, the useful area ratio is the collector opening (bounded by concha size) divided by the canal entrance (about 97 mm²). If the concha opening is only a few times the canal entrance (I found no concha-area source), the ideal ceiling is about 10·log10(3) ≈ 5 dB, for example.
- **The concha is already a horn.** The open ear's 10-20 dB natural gain (Section 2) comes from the concha and canal acting as collector and resonator. A concha horn is competing with that built-in horn, not adding to a blank baseline.
- **Viscous losses in 1 mm channels (calculation, Kirchhoff wide-tube approximation, ν = 1.5×10⁻⁵ m²/s):**

  | Frequency | Viscous boundary-layer thickness | Attenuation in a tube of 0.5 mm radius |
  |---|---|---|
  | 250 Hz | 0.14 mm | about 8 dB/m |
  | 1 kHz | 0.07 mm | about 16 dB/m |
  | 3 kHz | 0.04 mm | about 28 dB/m |

  A few centimetres of 1 mm channel costs only about 0.5-1 dB of straight-line attenuation. The larger cost is that the losses damp the resonant peaks that give a short horn its apparent gain, and printed surface roughness at the scale of the boundary layer (tens of µm) adds to them (not quantified in any source found). Treat any lossless simulation peak above about 10 dB at the throat with suspicion.
- **What is realistic, inferred from the above:** for a well-designed concha device, a few dB to perhaps 10 dB of re-shaped response in a band of about 1.5-4 kHz, before subtracting lost natural resonance. "Up to 10-20 dB" is defensible only for large external collectors such as trumpets and bells.

### Gaps
- No peer-reviewed frequency-response measurement (KEMAR or real ear) of any historical ear trumpet, hearing bell, or modern passive in-ear device was found. The AfH Lübeck figures carry no stated method.
- Amano Labs has published no gain or response data. EARCOUSTIC claims were not verified.
- No sourced value was found for concha cavum volume or opening area. The Shaw (1974) concha data was not fetched.
- The Kirchhoff loss figures and the exponential-horn cutoff formula are textbook results (Kinsler/Beranek/Webster) that I did not re-fetch.

## 2. Insertion loss: what a concha/canal device removes from the open ear

### Takeaway
The open adult ear gives about 10-20 dB of natural gain, peaking at about 2.7-3 kHz, plus a concha bump of 5-10 dB near 4-6 kHz. An occluding device can remove much of this, and up to 35 dB of attenuation has been reported for sealed earmolds. Net insertion gain = (horn response with the device in place) − (open-ear REUG). It can be zero or negative in exactly the 2-4 kHz band a short horn targets, unless the device stays acoustically open or beats the natural resonance.

### Cited Findings
- The typical adult REUG amplifies incident sound over about 1500-7000 Hz, peaking at about 2700-3000 Hz with roughly 10-20 dB of gain. The peak is linked to a canal of about 28 mm acting as a tube closed at the eardrum — [Interacoustics Academy](https://interacoustics.com/academy/hearing-aid-fitting-training/rem/what-should-an-adult-reug-look-like) (snippet, not fetched)
- "The typical REUG of an adult presents little or no amplification in the frequency region below 1500 Hz." The concha/shell contribution is about 10 dB in the 5-6 kHz region — [Thieme, Braz. J. Otorhinolaryngol./Int Arch ORL 2012](https://www.thieme-connect.com/products/ejournals/pdf/10.7162/S1809-97772012000300011.pdf) (snippet, not fetched)
- Concha resonance near 4000-5000 Hz "adds 5 dB to 8 dB of additional gain" — [Hearing Review, Chasin 2013](https://hearingreview.com/practice-building/practice-management/continuing-education/the-acoustics-of-hearing-aids-part-2-a-closer-look-at-boyle-s-law)
- Shaw's (1974) free-field-to-eardrum curve averages 12 investigations and is used as a reference REUG — [Valente et al., PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4168915) (snippet, not fetched)
- Insertion loss = REUR − REOR (unaided minus occluded response at the eardrum). Kopun et al. found snap-ring earmold attenuation "as much as 35 dB SPL for some subjects." Insertion loss with vented aids was partial above 2 kHz, and closed devices showed loss starting at about 0.6 kHz (Sweetow) — [Hearing Review, Wang 2004](https://hearingreview.com/practice-building/practice-management/big-assumptions-understanding-insertion-loss-in-hearing-aids)
- An earmold "changes the acoustic properties of the outer ear and of the ear canal and reduces the REUG." In one open-fit evaluation, the largest REUR-vs-REOR difference was about 3 dB at 2500-3500 Hz, meaning truly open fits barely change the natural response — [Hearing Review open-fit articles](https://hearingreview.com/hearing-products/accessories/earmolds/efficacy-of-an-open-fitting-hearing-aid) (snippet, not fetched; exact attribution among search results uncertain)
- Chasin attributes about 8 dB less needed high-frequency gain to deep fittings, partly because of microphone location: microphone placement in the concha adds 3-4 dB above 2 kHz — [Hearing Review, Chasin 2013](https://hearingreview.com/practice-building/practice-management/continuing-education/the-acoustics-of-hearing-aids-part-2-a-closer-look-at-boyle-s-law)

### Inferences
- The figure the project should report is **simulated REIG = (eardrum SPL with the device) − (eardrum SPL of the open ear)**, using the same simulated ear for both. Reporting "horn gain" against a bare tube or a free-field reference will overstate the benefit by roughly the 10-20 dB REUG.
- A horn cut off at 2-4 kHz (Section 1) puts its gain where the open ear already gives 10-20 dB. To break even, the device must reproduce that natural peak. Any surplus is the real benefit.
- Filling the concha also removes the concha's 5-10 dB contribution at 4-6 kHz unless the device's own geometry reproduces it.
- A large vent or open fit protects the natural REUG (less than 3 dB insertion loss in open-fit data). It also leaks horn output, so the horn's own gain falls at low and mid frequencies (Section 3).

### Gaps
- I did not obtain a primary table of mean REUG by frequency (Shaw 1974; Dillon's *Hearing Aids* tables). The commonly quoted "about 17 dB at 2.7 kHz" was not confirmed from a fetched primary source. Interacoustics' "10-20 dB at 2.7-3 kHz" is the best-sourced range.
- No measured insertion loss was found for a concha-filling, non-sealing shell specifically.

## 3. Occlusion effect, vent effects, residual canal volume

### Takeaway
A device that seals the canal raises own-voice low-frequency SPL by about 20-30 dB at 250 Hz when it seals shallowly in the cartilaginous canal. Deep bony-canal seals reduce this to about 0 dB. A concha device that seals at the canal entrance is the worst case. Vents of 2 mm or more relieve occlusion, but they also act as a high-pass leak for anything the horn delivers below about 1 kHz. The residual-volume (Boyle's law) gains quoted for hearing aids, 3-8 dB, assume a sound source sealed in the canal. They do not translate directly to a passive horn.

### Cited Findings
- Conventional hearing aids sealed in the cartilaginous canal produce an occlusion effect of 20-30 dB at 250 Hz, typically about 25 dB, "but varies by individual." A deep-fit earpiece sealed in the bony canal measured −10 to +5 dB, mean −3.6 dB, in 11 subjects at 250 Hz. "The shallower the insertion, the greater the occlusion effect." A vent of "at least 2 mm in diameter" is suggested to reduce occlusion — [Hearing Review, Staab 2003](https://hearingreview.com/hearing-products/accessories/earmolds/solving-the-occlusion-effect)
- An earmold sealing near the canal entrance produced more than 30 dB of occlusion effect, versus about 10 dB for a deeper seal. Doubling vent diameter cuts occlusion by about 12 dB but raises feedback risk by about 12 dB — Etymotic/Killion material, [AudiologyOnline OEM sell sheet](https://audiologyonline.com/files/content/05700/05788/oemsellsheet0900-p.pdf) (snippet, not fetched; attribution inferred from search result)
- A 2 mm vent reduced occlusion by 8.5 dB at 200 Hz but had no effect at 500 Hz (Revit) — search-result snippet, source among [Taylor & Francis occlusion summary](https://taylorandfrancis.com/knowledge/Medicine_and_healthcare/Otorhinolaryngology/Occlusion_effect) / [Hearing Review ampclusion](https://hearingreview.com/practice-building/practice-management/ampclusion-management-101-understanding-variables) (snippet, not fetched; exact source uncertain)
- At low frequencies, occluded-canal SPL is about 10-30 dB higher than the open canal. Occlusion is mainly a below-500 Hz phenomenon — [EPFL thesis on occlusion effect physics](https://infoscience.epfl.ch/record/187188?ln=en) / [Wikipedia: Occlusion effect](https://wikipedia.com/wiki/Occlusion_effect) (snippet, not fetched)
- Vent effectiveness is governed by acoustic mass, which depends on BOTH diameter and length. A shortened (Step-Vent) design gave more occlusion relief than a standard earmold of equal diameter. Occlusion and feedback place opposite demands on vent geometry — [RWTH Aachen publication](https://publications.rwth-aachen.de/record/1022701/files/1022701.pdf) and [US patent 7031484](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/7031484) (snippet, not fetched)
- A 3 mm vent produces a positive vent-associated resonance of up to 6-8 dB at roughly 1100-1500 Hz, just above the vent's low-frequency cut — [AudiologyOnline, Hayes 2004](https://www.audiologyonline.com/ask-the-experts/occlusion-effect-567)
- Residual volume is about 1.5 cc for a conventional fitting and about 0.5 cc for a deep canal fitting. Chasin states "each halving of the volume increases the sound pressure by 3 dB." He puts the Boyle's-law contribution of a deep fit at "up 4-5 dB," with net low-frequency benefit "only around 1 dB" because eardrum compliance makes the volume look larger at low frequencies — [Hearing Review, Chasin 2013](https://hearingreview.com/practice-building/practice-management/continuing-education/the-acoustics-of-hearing-aids-part-2-a-closer-look-at-boyle-s-law)
- **Conflict:** Phonak's audiology blog states that halving a hard-walled cavity's volume raises pressure by about 6 dB, the ideal Boyle's-law value. It reports that deeper molds increase output at the eardrum by up to 8 dB in ear-model measurements — [Phonak Audiology Blog](https://audiologyblog.phonakpro.com/?p=29108) (snippet, not fetched). Chasin's 3 dB per halving and the ideal 6 dB per halving disagree. The real ear sits between them because of eardrum compliance.
- CIC coupler measurements use a smaller coupler, about 0.4 cc, with software corrections — [search results, Hearing Review / Hearing Health Matters "Wayne's World"](https://hearinghealthmatters.org/waynesworld/2012/ric-hearing-aid-coupler-measurement-correction) (snippet, not fetched)

### Inferences
- **Vent dilemma for a passive horn.** A tight seal maximizes horn pressure at low and mid frequencies but adds 20-30 dB of own-voice boom and blocks the natural REUG. A 2-3 mm vent removes most occlusion below about 500 Hz and leaks horn output below about 1 kHz. A passive horn has no feedback problem (no amplifier loop), which is one real advantage over electronic aids: the vent can be as large as the gain target allows.
- **Residual-volume gain does not apply here.** The Boyle's-law numbers assume a constant-volume-velocity receiver. A passive horn behaves more like a pressure transmission path into a resonant canal. A smaller residual volume mainly shifts canal resonances. Simulations should model the canal plus an eardrum impedance, not assume "+X dB per cc."
- The simulation should report own-voice occlusion (bone-conducted excitation of the canal walls) as a separate metric. A standard air-conduction FEM/BEM horn model will not capture it.

### Gaps
- Dillon's vent-effect tables (gain change vs vent diameter and frequency) were not accessible. No primary vent-diameter-vs-dB table was fetched.
- No occlusion data was found for concha-only devices with no canal portion.

## 4. Target population and prescriptive gain vs a passive ceiling

### Takeaway
Half-gain logic (gain ≈ 0.46-0.5 × threshold) implies that a mild loss of 26-40 dB HL needs roughly 13-20 dB of insertion gain at the affected frequencies (calculation). NAL-NL2 prescribes about 3 dB less than NAL-NL1 at 65 dB SPL and little or no gain for near-normal thresholds. A real 5-10 dB net insertion gain in a narrow 2-4 kHz band is therefore plausibly useful only for mild, high-frequency-sloping loss. It falls well short of "mild-to-moderate" (up to about 55-60 dB HL), which would need about 25-30 dB.

### Cited Findings
- The half-gain rule (Lybarger, 1940s) sets insertion gain at about half the air-conduction threshold. A 1980 study of nearly 500 sensorineural clients found it held, "except with mild losses, where the obtained gain was a bit under half the threshold" — [Medline abstract, BVS](https://pesquisa.bvsalud.org/brasil/resource/en/mdl-7409361) (snippet, not fetched); [AudiologyOnline 20Q](https://audiologyonline.com/articles/20q-same-or-different-comparing-769?print=true) (snippet, not fetched)
- Byrne's NAL data put preferred/used gain at about 0.46 × threshold, the basis of NAL's formula — [AudiologyOnline, Denis Byrne at NAL](https://www.audiologyonline.com/articles/research-denis-byrne-at-nal-1200) (snippet, not fetched)
- NAL-NL2 provides about 3 dB less overall gain than NAL-NL1 for mild and moderate loss at 65 dB SPL input, with more compression — [Forum Acusticum 2023 paper](https://dael.euracoustics.org/confs/fa2023/data/articles/000453.pdf) (snippet, not fetched)
- NAL-NL2 prescribes no insertion gain for people with minimal hearing loss but significant speech-in-noise difficulty — [Hearing Review, NAL-NL3 article](https://hearingreview.com/hearing-products/testing-equipment/fitting-equipment/nal-nl3-advancing-hearing-aid-prescription-for-modern-clinical-practice) (snippet, not fetched)
- In real-ear verification, 55% of manufacturer "NAL-NL2" first fits were 10 dB or more below target at one or more frequencies (250-4000 Hz) for 65 dB SPL input — [Hearing Review 2015](https://hearingreview.com/hearing-products/testing-equipment/manufacturers-nal-nl2-fittings-fail-real-ear-verification) (snippet, not fetched)
- WHO (fact sheet dated 3 March 2026): over 5% of the world's population, 430 million people including 34 million children, require rehabilitation for disabling hearing loss, defined as greater than 35 dB in the better ear. Normal hearing is 20 dB or better in both ears. By 2050 nearly 2.5 billion people are projected to have some degree of hearing loss, and more than 700 million will need rehabilitation — [WHO fact sheet](https://www.who.int/news-room/fact-sheets/detail/deafness-and-hearing-loss)

### Inferences
- Half-gain/NAL-style targets (calculation, gain ≈ 0.46-0.5 × HL):

  | Threshold | Required gain |
  |---|---|
  | 30 dB HL | about 14-15 dB |
  | 40 dB HL | about 18-20 dB |
  | 55 dB HL | about 25-28 dB |

  NAL-NL2 targets for a 65 dB SPL input in mild loss are usually somewhat lower than half-gain at low frequencies and closer to it in the 2-4 kHz band. Exact values need the NAL-NL2 software.
- Best-fit candidates for the claim: adults with mild (about 25-40 dB HL) loss that is flat-to-high-frequency-sloping in the 2-4 kHz region. Good low-frequency hearing makes a large vent acceptable, and they do not need gain below 1 kHz. Avoid claiming benefit for moderate loss, low-frequency loss, or any loss needing more than about 10 dB.
- People with mild loss (26-40 dB HL in the WHO "mild" band) fall below WHO's ">35 dB" disabling threshold, so the 430 M figure does not count most of them. Do not cite 430 M as the addressable market for a mild-loss device.

### Gaps
- No exact NAL-NL2 per-frequency insertion-gain table for a standard mild sloping audiogram (e.g., N2/N3 standard audiograms, Bisgaard et al. 2010) was fetched.
- Lancet / GBD 2019 global count of all hearing loss (about 1.57 billion), and untreated-loss rates (hearing-aid uptake), were not fetched in this pass. Do not cite them without a primary source.

## 5. Regulation: OTC hearing aid rule, PSAP, and passive devices

### Takeaway
Under 21 CFR 800.30, a "hearing aid" is ANY wearable device "designed for, offered for the purpose of, or represented as aiding persons with or compensating for, impaired hearing," with no electronic requirement. Marketing a passive horn "for mild-to-moderate hearing loss" (as Amano does) therefore most likely makes it an air-conduction hearing aid under 21 CFR 874.3300. That is Class I and 510(k)-exempt, with general controls, labeling, and, if sold OTC, the 800.30 performance and labeling requirements. Several of those requirements are written for electronic devices. I found no FDA product code specific to ear trumpets or non-electric aids.

### Cited Findings
- "A hearing aid is any wearable device designed for, offered for the purpose of, or represented as aiding persons with or compensating for, impaired hearing." "An air-conduction hearing aid is a hearing aid that conducts sound to the ear through the air." An OTC hearing aid is an air-conduction hearing aid, not implanted, for persons 18+ "to compensate for perceived mild to moderate hearing impairment" — [21 CFR 800.30, LII](https://www.law.cornell.edu/cfr/text/21/800.30)
- OTC output limit: 111 dB SPL at any frequency, or 117 dB SPL with input-controlled compression active. Electroacoustic requirements: THD+N at most 5%, self-generated noise at most 32 dBA, latency at most 15 ms, lower cutoff at or below 250 Hz, upper cutoff at or above 5 kHz. The insertion limit keeps the most medial component at least 10 mm from the tympanic membrane — [21 CFR 800.30, LII](https://www.law.cornell.edu/cfr/text/21/800.30)
- §874.3300 Air-conduction hearing aid: "a wearable sound-amplifying device intended to compensate for impaired hearing" that "conducts sound to the ear through the air." It is Class I (general controls) and exempt from premarket notification subject to §874.9. It is subject to §800.30 or §801.422 as applicable — [21 CFR 874.3300, LII](https://www.law.cornell.edu/cfr/text/21/874.3300)
- Product codes listed by third-party mirrors: ESD (air-conduction hearing aid, prescription) and QUF (air-conduction, OTC) under 874.3300, both Class I. QUG is a wireless OTC air-conduction hearing aid under 874.3305, Class II. KHL (master hearing aid) is under 874.3330, Class II — [ai-analytics QUF](https://api.ai-analytics.org/device-classification/QUF), [regdatalab QUG](https://www.regdatalab.com/device-class/QUG) (third-party mirrors, not fetched; verify on FDA accessdata). No ear-trumpet or non-electric product code was found.
- The final rule was published in August 2022 and took effect October 17, 2022. The output cap was lowered from the proposed 115 to 111 dB SPL. Severe loss and children remain prescription — [ASHA news](https://asha.org/news/2022/fda-releases-final-rule-for-otc-hearing-aids), [MedTech Dive](https://www.medtechdive.com/news/fda-final-rule-OTC-hearing-aids/629769/) (snippet, not fetched)
- FDA's companion PSAP guidance: PSAPs are consumer products to accentuate sounds for non-hearing-impaired listeners, and explicit or implicit claims of addressing hearing loss make a product a hearing aid — [MedTech Dive / ASHA coverage](https://www.medtechdive.com/news/fda-final-rule-OTC-hearing-aids/629769/) (snippet, not fetched)

### Inferences
- A passive device cannot exceed 111 dB SPL in practice, because it cannot output more than the incoming sound plus about 10-20 dB. The output limit is moot. Latency (about 0 ms) and distortion (linear) are also trivially met. The 250 Hz-5 kHz bandwidth requirement could be a problem: a concha horn with a 2-4 kHz cutoff and a large vent may not "extend" to 250 Hz in any gain sense. How FDA would apply that test to a non-electronic device is unclear (gap).
- Honest hackathon framing: a "research prototype, not a medical device; not evaluated by FDA." Avoid "hearing aid," "treats/compensates for hearing loss," or "for mild-to-moderate hearing loss" in public claims unless the team accepts hearing-aid status. Even a PSAP framing does not allow hearing-loss claims.
- Note §874.9 limitations on exemption (not fetched). Exemption can be lost for devices with different technology or intended use.

### Gaps
- §874.9 exemption-limitation text, and whether FDA considers a non-electric horn the "same fundamental scientific technology," were not checked.
- The full 2022 final-rule Federal Register preamble discussion (if any) of non-electronic or acoustic-only devices was not fetched. eCFR blocked automated access.
- No FDA 510(k)/registration listing for Amano Labs or similar passive devices was found.

## 6. Validation: what an honest simulation claim is, and how to measure cheaply

### Takeaway
Simulation alone supports only "predicted change in eardrum SPL relative to the simulated open ear, in a lossless (or loss-modeled) model of one ear geometry," with explicit error bars. Clinical claims require coupler and real-ear insertion-gain measurement against the open-ear REUR. The industry standard is probe-tube REM (REUR → REAR → REIG) using a phantom or real ear, with the device inserted and removed and everything else unchanged.

### Cited Findings
- Insertion loss/gain are defined from probe-tube measurements at the eardrum: REUR (open), REOR (device in, off), and REAR. Insertion loss = REUR − REOR. A device is "truly open" when REUR ≈ REOR — [Hearing Review, Wang 2004](https://hearingreview.com/practice-building/practice-management/big-assumptions-understanding-insertion-loss-in-hearing-aids)
- KEMAR with anthropometric pinnae matched a median human ear well up to about 8 kHz, with larger deviations above that (Hearpiece database) — [Acta Acustica 2021](https://acta-acustica.edpsciences.org/articles/aacus/full_html/2021/01/aacus200022/aacus200022.html) (snippet, not fetched)
- Individual REUR differs from average. If the REUR is larger than average, measured REIR falls, an apparent insertion loss — [Hearing Review search results on REUR/insertion loss](https://hearingreview.com/practice-building/practice-management/big-assumptions-understanding-insertion-loss-in-hearing-aids) (snippet)
- CIC/deep-fit coupler measurement uses a smaller coupler of about 0.4 cc with corrections. The standard 2 cc coupler does not represent the real-ear load — [Hearing Health Matters, Wayne's World](https://hearinghealthmatters.org/waynesworld/2012/ric-hearing-aid-coupler-measurement-correction) (snippet, not fetched)

### Inferences
These are recommendations derived from the definitions above, not sourced protocols.
- **Cheap A/B protocol for a hackathon:**
  1. Print a simple ear simulator: a rigid tube of about 7.5 mm diameter and 25-30 mm length (matching the CT canal dimensions), ending in a small calibrated measurement mic. A $10-30 lavalier or MEMS mic is better than a phone mic because phone mics have AGC/noise suppression that must be disabled.
  2. Optionally attach a printed pinna/concha from the patient mesh.
  3. Play a swept sine or pink noise from a speaker about 1 m away at a fixed position.
  4. Record (a) open simulator, (b) simulator with the printed horn, and (c) simulator with a solid plug of the same outer shape.
  5. Report (b) − (a) as "insertion gain on our simulator," and (c) − (a) as insertion loss.

  Every measurement is relative (same mic, same speaker, same position), so the mic needs no absolute calibration.
- What this cannot validate: absolute eardrum SPL. A rigid tube lacks eardrum impedance, so its resonance Q and peak height will exceed a real ear's, and IEC 60318-4 occluded-ear simulators exist to model that impedance. Nor can it show individual-ear fit, own-voice occlusion, or speech benefit (which needs aided thresholds or speech-in-noise testing on people, an IRB matter).
- An honest simulation claim looks like: "In a [lossless / viscothermal] model of one ear geometry, the device is predicted to change eardrum SPL by +X dB at Y-Z kHz relative to the open ear, and by −W dB elsewhere. Not measured; not clinically validated."

### Gaps
- No fetched source gave IEC 60318-4 specifications, cost, or a validated DIY ear-simulator build. No published smartphone-microphone REM validation was found in this pass.
- No sourced guidance was found on test-retest variability of DIY coupler measurements. As a rule, ±2-3 dB repeatability between insertions is typical in clinical REM, but this was not sourced here.

## 7. 3D printing realities: channel size, roughness, biocompatible resins

### Takeaway
Earmold-grade biocompatible resins exist and are used commercially, for example Formlabs BioMed Clear for hard earmolds and shells, Dreve FotoTec DLP.A, and Liqcreate Bio-Med Flex. Their ISO 10993 claims hold only for the validated printer, settings, wash and cure workflow. I found no sourced minimum printable vent or channel diameter. Surface roughness at layer scale (25-100 µm) is the same order as the acoustic boundary layer (40-140 µm, my calculation), so printed 1 mm channels will be lossier than smooth-tube models predict.

### Cited Findings
- Formlabs BioMed Clear is marketed for hard earmolds, shells and in-ear monitors. It is produced in an ISO 13485 facility with an FDA Device Master File. Its test data come from samples printed on a Form 3B at 100 µm with specified washing and post-cure, and results depend on print settings and sterilization — [Formlabs medical materials](https://formlabs.com/materials/medical), [Formlabs blog: biocompatible resin for audio](https://formlabs.com/eu/blog/biocompatible-audio-applications/) (snippet, not fetched)
- Liqcreate Bio-Med Flex reports passing ISO 10993-5, -10 and -23 only when parts follow its specified workflow — [3D Printing Industry](https://3dprintingindustry.com/news/liqcreates-bio-med-flex-now-enables-flexible-and-sterilizable-3d-printed-parts-253035/) (snippet, not fetched)
- Dreve FotoTec DLP.A is a biocompatible earmold resin for DLP printing — [Dreve Otoplastik](https://otoplastik.dreve.de/en/highlights/3d-printing-resins) (snippet, not fetched)
- Uncured resin, support residue and layer-line roughness can affect biocompatibility even when the base material has test data, and claims may apply only to the validated printer/parameters — [CASRAI biocompatible 3D printing guide](https://casrai.org/guides/biocompatible-3d-printing-materials) (snippet, not fetched)
- OC GmbH and Caddent 3D-print patient-specific earmolds commercially — [VoxelMatters](https://www.voxelmatters.com/oc-gmbh-and-caddent-3d-print-patient-specific-earmolds.md) (snippet, not fetched)

### Inferences
- A 1 mm × 1 mm channel (patent throat) is printable on SLA/DLP at 25-100 µm layers, but resin can trap and partially cure inside long, coiled, sub-2 mm channels. Washing internal passages is a known SLA difficulty, and residual uncured resin is also the biocompatibility risk the CASRAI guide names. Prefer channels of about 1.5-2 mm or more, with open, flushable paths, unless printing tests show otherwise. This is a design heuristic, not sourced.
- FDM-printed horns have stair-step roughness of hundreds of µm and porous walls. They are unsuitable for in-ear use and acoustically lossy.
- Use "printed in a resin with ISO 10993 test data, e.g., BioMed Clear," not "biocompatible device." The device-level claim requires the validated workflow and device-level testing.

### Gaps
- No source quantified acoustic loss versus surface roughness for printed tubes, or gave a minimum vent/channel diameter for earmold printers.
- Shrinkage and dimensional tolerance of earmold resins (relevant to fit and channel area) was not fetched.
