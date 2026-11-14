# Sound source angle and spatial effects for a passive in-concha horn hearing aid

Scope: whether speaker azimuth and elevation matter for a passive, 3D-printed horn that sits in the concha and couples into the ear canal, how large the effects are in dB, and the cheapest credible way to model them in a weekend simulation.

Source quality note: Web access to several primary papers (Shaw 1974 full text, Ricketts 2001, Bronkhorst and Plomp 1988, the CID Aurolese measurement) was not possible. Where a number comes from a secondary source citing a primary paper, that is flagged. Numbers recalled from textbook knowledge but NOT confirmed against a fetched source are placed under Inferences or Gaps and marked "unverified".

## Q1. Head shadow, HRTF, and interaural level differences vs frequency and azimuth

### Takeaway
Source angle changes the level at one ear by up to about 15 dB in the speech-relevant 2 to 8 kHz range. Below about 1 kHz the head is acoustically small and angle matters little. Most of the roughly 10 dB spatial benefit for speech in noise comes from head shadow (level differences), not from fine binaural timing.

### Cited Findings
- Shaw (1974), "Transformation of sound pressure level from the free field to the eardrum in the horizontal plane," JASA 56(6):1848-1861, pooled data from 12 studies into average free-field-to-eardrum curves at 15-degree azimuth steps over 0.2 to 12 kHz. It covers eardrum transformation, azimuthal dependence and interaural differences. It is the standard reference table. — [PubMed 4443484](https://pubmed.ncbi.nlm.nih.gov/4443484/); [Scilit record](https://scilit.com/publications/96aa7e4eebffdc0ec0fdf14dabe9dfb7)
- A companion Shaw paper gives the same data in numerical form: azimuthal dependence tabulated at 15-degree intervals, and the 0-degree transformation at 43 frequencies from 0.2 to 12 kHz. This is a ready-made lookup table for a simulation. — [Scilit: "...presented in numerical form"](https://scilit.com/publications/282faeae31950eea1af13ea3d0bb0556)
- Frontal-incidence response is similar to the diffuse-field response except at very high frequencies (7 to 10 kHz). — summary of Shaw curves in [JCAA lecture PDF](https://jcaa.caa-aca.ca/index.php/jcaa/article/download/441/103/493) (via search snippet; the PDF is scanned and could not be machine-read)
- Sounds from 180 degrees (behind) are less intense at the ear than sounds from 0 degrees above about 1 kHz (Shaw 1974, as cited). No dB value given in the text. — [AudiologyOnline, Hallenbeck and Groth 2011](https://www.audiologyonline.com/articles/evidence-based-design-leads-to-792)
- A single-subject in-ear and BTE measurement showed spectral changes of "up to approximately 15 dB relative to the front direction" for sources at 45 and 120 degrees. — [Jensen et al. 2013, Trends in Amplification 17(3-4):171-188](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)
- The spatial-separation benefit for speech in noise is on the order of 10 dB, of which roughly 2 to 3 dB is due to binaural timing (IPD) processing and the rest to head shadow (Bronkhorst 2000, citing Bronkhorst and Plomp 1988, Plomp and Mimpen 1981). Secondary citation; not checked against the 1988 paper. — [Shinn-Cunningham et al. 2001, JASA](https://www.cmu.edu/dietrich/psychology/shinn/publications/pdfs/2001/2001jasa_shinn.pdf)
- In a replication with the HINT test, level differences alone gave about 3.97 dB of SRT improvement and time differences alone about 3.22 dB, both relative to 0 degrees (Nilsson, Jayaraman and Soli 1993). — [ASA 126th meeting abstract, 1993](https://auditory.org/asamtgs/asa93dnv/5pSP/5pSP7.html)
- The head shadows laterally arriving sound, producing level differences that allow "better-ear listening," the main driver of spatial release from masking. — [PMC5014088](https://pmc.ncbi.nlm.nih.gov/articles/PMC5014088)

### Inferences
- Unverified (textbook recall of Shaw 1974 curves): interaural level difference reaches roughly 15 to 20 dB at 90 degrees for frequencies around 4 to 10 kHz, is under about 5 dB below 500 Hz, and the ipsilateral ear at 90 degrees gets a few dB MORE level than at 0 degrees in the mid frequencies. This matches the user's prior and the 15 dB spectral-change figure from Jensen et al. 2013, but the exact table values should be read from the Shaw numerical-form paper.
- For a single-ear passive device the relevant quantity is NOT the interaural difference but the ipsilateral level change vs angle (horn ear facing or turned away from the talker). That change is roughly half the interaural difference on each side: a talker on the aided side gains a few dB, a talker on the far side loses up to about 10 to 15 dB at 2 to 8 kHz.
- Since the head shadow already exists with or without the horn, a horn that is roughly omnidirectional at the ear entrance will inherit the same angle dependence as the open ear. Angle affects the absolute level reaching the device far more than it affects the device's gain.

### Gaps
- Exact Shaw (1974) dB values per azimuth and frequency were not retrieved (full text paywalled; JCAA PDF is a scan). The numerical-form companion paper is the source to pull.
- Bronkhorst and Plomp (1988) original numbers were not checked; the 10 dB figure is second-hand.

## Q2. Pinna and concha acoustics, open-ear gain, and the cost of filling the concha

### Takeaway
The open ear provides about 15 to 20 dB of natural gain, peaking near 2.7 kHz from the ear canal resonance, with the concha sustaining the response for about another octave toward 5 kHz. Any device that fills the concha or blocks the canal entrance removes some of this free gain (insertion loss), and the passive horn must exceed that loss before it provides any net benefit.

### Cited Findings
- The peak of the open-ear response is at about 2700 Hz, and the "gain" from the unoccluded ear canal and concha is on the order of 15 to 20 dB. — [AudiologyOnline, "Common clinical encounters"](https://www.audiologyonline.com/articles/common-clinical-encounters-59-but-909) (via search snippet)
- Shaw's measurements put the primary external-ear resonance at about 2.6 kHz, "not at 4 kHz as frequently stated," with a strong concha resonance that sustains the response for almost one octave above the peak. — [JCAA paper on Shaw's work](https://jcaa.caa-aca.ca/index.php/jcaa/article/download/441/103/493) (via search snippet)
- Shaw (1997 ASA abstract): the concha's role is clearest between 5 and 10 kHz; pinna diffraction effects are strong between 2.5 and 6 kHz. — [auditory.org ASA 1997 abstract](https://auditory.org/asamtgs/asa97snd/2pSP/2pSP1.html)
- One clinical blog describes a "concha-related resonance" at about 4500 to 5500 Hz (the author speculates it may be a half-wavelength canal mode; that is his hypothesis, not an established finding). — [Hearing Health Matters, "Is the human ear canal a cylinder or a cone? Part 2"](https://hearinghealthmatters.org/hearthemusic/2016/3193/)
- Blocking the outer portion of the ear canal (wax, collapsed cartilage) significantly reduces the 2700 Hz resonance. — [Hearing Health Matters, standing waves](https://hearinghealthmatters.org/hearthemusic/2014/acoustics-hearing-aids-standing-waves-part-1) (via search snippet)
- Real-ear unaided gain (REUG) reflects ear canal resonance at about 2 to 3 kHz. An earmold changes the acoustics of the outer ear and canal and reduces REUG; more open fittings keep more of the natural canal resonance and so need less device gain. — [Winkler et al. 2016, Trends in Hearing (open vs closed fittings)](https://www.phonak.com/content/dam/phonak/en/evidence-library/journal-article/Trends_in_Hearing-2016-Winkler-Open_versus_closed_fittings.pdf); [Hearing Review, REM for non-occluding fittings](https://hearingreview.com/hearing-loss/patient-care/hearing-fittings/demystifying-rem-verification-for-non-occluding-fittings)
- Insertion gain is defined as aided response minus unaided response (REIG = REAR - REUR), so the open-ear gain is the baseline a device must beat. — [Hearing Review, REM for non-occluding fittings](https://hearingreview.com/hearing-loss/patient-care/hearing-fittings/demystifying-rem-verification-for-non-occluding-fittings)
- Insertion loss is described as distortion or elimination of the natural concha and ear canal resonances; one patent claims a design keeping it below about 3 dB vs the unaided ear (patent claim, not an independent measurement). The same patent says a custom earmold can boost low-frequency own-voice level by about 20 to 30 dB (occlusion effect). — [EP1988743 patent](https://data.epo.org/publication-server/rest/v1.2/patents/EP1988743NWA2/document.html)

### Inferences
- Unverified (textbook recall, Shaw 1974 / Dillon "Hearing Aids"): average REUG peak is about 17 dB near 2.7 kHz, and the concha contributes a resonance of roughly 10 dB around 5 kHz. These are consistent with the 15 to 20 dB range cited above but were not confirmed as exact figures.
- For the horn design, the simulation's baseline must be the OPEN EAR at the same angle, not a free-field microphone. A horn that delivers 10 dB at the canal entrance but kills a 10 to 17 dB natural resonance gives zero or negative insertion gain at 2 to 5 kHz.
- A horn that fills the concha removes the concha's 5 kHz resonance and much of the pinna's direction-dependent filtering. If the horn mouth sits at the concha opening, it will still see the head-shadow pattern but lose the pinna's high-frequency front/back cues.
- Leaving a vent or keeping the canal partly open preserves canal resonance and avoids the occlusion effect; the horn's throat termination in the canal is therefore as important as its mouth.

### Gaps
- No source found giving a per-frequency insertion-loss table for a concha-filling passive device.
- The concha resonance gain value (commonly quoted near 10 dB at 5 kHz) could not be confirmed from a fetched source.

## Q3. Microphone location effects (MLE): BTE vs ITE vs ITC vs CIC

### Takeaway
The deeper the sound inlet sits in the pinna, the more of the natural front/back and elevation cues survive. A CIC or concha-located inlet clearly reduces front-back confusions compared with a BTE microphone above the pinna, while left-right localization is unaffected by style. A concha horn is acoustically closer to an ITE/CIC inlet than to a BTE.

### Cited Findings
- CIC aids (mic at canal entrance) produced fewer front-back reversals than BTE aids (mic above the pinna) in hearing-impaired listeners; left-right and vertical errors did not differ. Small sample (11 listeners). — [Best et al. 2010, Int J Audiol, PubMed 20515424](https://pubmed.ncbi.nlm.nih.gov/20515424/)
- Moving the microphone from above the ear into the concha (CIC setting) reduced front-back RMS localization error by a mean of 22 degrees (SD 19 degrees); 13 of 17 participants improved by at least 15 degrees; CIC-setting front-back RMS errors ranged 25 to 83 degrees. Left-right error changed by only 3 degrees (not significant). — [Jensen et al. 2013, Trends in Amplification](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)
- In the same study, front-back spatial release from masking was about 0.9 dB higher with the in-concha mic (not significant); the front-back SRT benefit was about 1.2 dB, smaller than the roughly 3 dB "pinna shadow" the authors estimated. — [Jensen et al. 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)
- A BTE microphone above the pinna loses the high-frequency spectral notches that vary with elevation and angle, so front vs back cannot be told apart. — [US patent 8107654 (mixing in-ear and outside-ear mics)](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8107654); [Hearing Review 2009, aided localization](https://hearingreview.com/2009/09/a-new-technique-to-improve-aided-localization/)
- A microphone in the cymba of the concha keeps the outer ear's directivity, and front-back confusions were reduced with this placement (Van den Bogaert et al. 2011, as cited). Manufacturer-authored. The same placement gave about 9 dB more gain before feedback than standard CICs in 26 real ears, and up to 5 dB more on KEMAR. — [AudiologyOnline, Hallenbeck and Groth 2011](https://www.audiologyonline.com/articles/evidence-based-design-leads-to-792)
- An ITC device measured about 1.3 dB higher sAI-DI than a RIC device, attributed to the added pinna effect. — search summary of [Canadian Audiologist 2015, "Measuring directionality of modern hearing aids"](https://canadianaudiologist.ca/measuring-directionality-of-modern-hearing-aids/) (snippet only)

### Inferences
- For a passive horn, the "microphone location" is the horn mouth. If the mouth sits in the concha bowl facing out, it behaves like an ITE/CIC inlet: pinna cues are partly preserved and front-back separation is better than a BTE location. If the horn projects outward beyond the tragus or above the pinna, it will behave more like a BTE and lose front/back cues.
- The localization benefit of an in-concha inlet is mostly front vs back (tens of degrees of error), not left vs right, and its speech-in-noise effect is about 1 dB. That puts MLE in the second-order category for speech benefit.

### Gaps
- No single verified table of MLE in dB by frequency for BTE/ITE/ITC/CIC on KEMAR was retrieved (the classic Bentler/Pavlovic and ANSI S3.35 tables were not accessible). Fortune (1997) was not found.

## Q4. Directional benefit: DI and AI-DI of the open ear, ITE, BTE, directional mics

### Takeaway
On a real head, first-order directional microphones reach only about 2 to 3.5 dB DI, roughly 3 dB below their free-field values, because the head and pinna disturb the field. An omnidirectional inlet in the canal or concha has near-zero AI-DI; the open pinna adds only a small positive DI at high frequencies. Directivity differences between omni locations are worth about 1 dB, not 5 to 10 dB.

### Cited Findings
- KEMAR-measured average DI (Dittberner and Bentler 2003): first-order cardioid about 2.3 to 2.7 dB, hypercardioid about 3 to 3.3 dB, supercardioid about 3.3 to 3.5 dB (BTE/ITE); second-order patterns about 6 to 7.4 dB. Theoretical (free-field) values are about 3 dB higher. Column alignment in the fetched table was ambiguous, so BTE vs ITE assignment is uncertain. — [Hearing Review, "Interpreting the Directivity Index"](https://hearingreview.com/practice-building/practice-management/interpreting-the-directivity-index-di)
- Free-field DI for the same nominal pattern can differ by 3 dB or more across manufacturers; "the head, pinna, and torso will have an effect on the directivity" of ITE and BTE mics. — [Dittberner and Bentler 2003](https://hearingreview.com/practice-building/practice-management/interpreting-the-directivity-index-di)
- A vendor patent quotes typical BTE AI-DI of about 2 to 3 dB (limited by pinna shadow) vs about 5 dB for a directional ITE, and says canal-located mics show typical AI-DI of about -0.5 to 0.2 dB because they sit in the resonant part of the canal. Vendor claims. — [US patent 6704423](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6704423)
- An omnidirectional microphone has DI 0 dB in a test chamber (by definition). AI-DI weights frequencies by speech importance, e.g. 2000 Hz over 500 Hz. — [Canadian Audiologist, evolution of directionality](https://canadianaudiologist.ca/evolution-of-directionality-feature/?output=pdf); [Canadian Audiologist, measuring directionality](https://canadianaudiologist.ca/measuring-directionality-of-modern-hearing-aids/)
- Directional DI drops significantly below 1000 Hz in vented fittings (Ricketts 2005, 12 aids). — [Hearing Review, "Is real-world directional benefit predictable"](https://hearingreview.com/hearing-products/accessories/earmolds/is-real-world-directional-benefit-predictable)
- Some CIC users do well in noise because deep placement keeps the natural pinna directivity. — [AudiologyOnline, Hallenbeck and Groth 2011](https://www.audiologyonline.com/articles/evidence-based-design-leads-to-792)

### Inferences
- Unverified (recall of Ricketts 2001, Trends in Amplification 5:139-176, and Mueller and Ricketts tables): the open ear on KEMAR has AI-DI around 0 to 1 dB, with pinna DI of about 2 to 4 dB around 3 to 6 kHz and slightly negative values at low frequencies; BTE omni AI-DI is about -1 to 0 dB; ITE/CIC omni is close to the open ear. These are plausible given the cited KEMAR and patent numbers but need the original tables.
- A passive omni horn in the concha should therefore land near the open ear's AI-DI (roughly 0 to 1 dB). It will NOT provide the 2 to 4 dB of a directional microphone unless its mouth is large compared with the wavelength (see Q5).

### Gaps
- Ricketts (2001) Trends in Amplification text with unaided-ear AI-DI was not retrieved.
- No source found reporting a DI for any passive horn or ear trumpet.

## Q5. Does a horn mouth facing outward add directivity? Ear trumpet literature

### Takeaway
Measured data on ear trumpet directivity is essentially absent from the accessible literature. Physics says a mouth only a few centimetres across is nearly omnidirectional below about 5 kHz, so an in-concha horn adds little directivity in the speech band. Historical trumpets gave about 10 dB over a limited band, and only large mouths collected meaningfully more sound.

### Cited Findings
- The Aurolese Phone (a 19th-century headband ear trumpet) was measured by researchers at the Central Institute for the Deaf (2003); the exhibit summary puts its benefit at up to about 10 dB over a limited frequency range, suitable for mild loss. Secondary source; the measurement paper itself was not retrieved. — [Becker Library, Aurolese Phone](https://becker.wustl.edu/?p=17889)
- Ear trumpets work by collecting sound over a wide opening and funneling it to the ear; a collector/engineer found the wide end has to be much larger than the ear to gather meaningfully more sound, and his own 1800s trumpet was "nearly useless." Acoustic aids varied widely: some worked, some were essentially useless. — [Canadian Audiologist, history of the ear trumpet](https://canadianaudiologist.ca/a-brief-history-of-the-acoustic-ear-trumpet-and-some-collection-favourites/); [Canadian Audiologist, hearing aids of yesteryear](https://canadianaudiologist.ca/the-hearing-aids-of-yesteryear/?output=pdf)

### Inferences
- Physics (standard piston/horn directivity, not from a fetched source): a radiating or receiving aperture becomes directional when ka > 1, where k = 2*pi*f/c and a is the mouth radius. For a 2 cm diameter mouth, ka = 1 at about 5.5 kHz; for 4 cm, about 2.7 kHz. So an in-concha horn sized to fit the bowl (mouth 1.5 to 2.5 cm) is close to omnidirectional across most of the speech band, and will contribute at most a dB or two of directivity at 4 to 8 kHz.
- To get directivity of a few dB at 1 to 2 kHz, the mouth would have to be about 10 to 20 cm across (ear-trumpet scale), which is incompatible with an in-concha form factor.
- A forward-facing mouth may increase the level for a front talker relative to a rear source only at high frequencies; the main angle effect will still be head shadow.

### Gaps
- No measured polar data for ear trumpets or concha horns was found. The CID 2003 Aurolese study and any KEMAR measurement of acoustic horns would be the sources to obtain.
- A search result mentioned an "artificial concha device" with about 13 dB gain near 1.5 kHz, but the originating source could not be identified, so it is excluded.

## Q6. Spatial release from masking (SRM): size of the benefit and the effect of hearing loss and aids

### Takeaway
Separating a talker from a masker gives normal-hearing listeners about 5 to 10 dB of SRT improvement (larger for speech maskers with real separation), mostly from head shadow. Hearing loss cuts this to around 2.7 dB or to nothing, and bilateral aids preserve more of it than unilateral aids. A single passive horn on one ear cannot restore binaural timing benefit, but by adding high-frequency audibility on the aided side it can help better-ear listening.

### Cited Findings
- Spatial separation benefit for unfiltered speech: 6.1 dB for younger normal-hearing, 4.9 dB for older normal-hearing, 2.7 dB for older hearing-impaired listeners (Dubno et al. 2002). — [Dubno, Ahlstrom and Horwitz 2002, JSLHR](https://pubs.asha.org/doi/10.1044/1092-4388(2002/104))
- With real (loudspeaker) spatial separation, mean SRM ranged 7.1 to 11.4 dB depending on speech corpus; with only perceived separation, 1.8 to 3.1 dB. — [King, Corbin, Leibold and Buss, JAAA](https://www.thieme-connect.de/products/ejournals/pdf/10.3766/jaaa.19018.pdf)
- A model-based (FADE/DARF) simulation found about 5 dB SRM with a stationary masker and about 2 dB with a fluctuating masker for normal hearing, and no SRM for the simulated hearing-impaired configuration. — [DARF, arXiv 2007.05378](https://arxiv.org/pdf/2007.05378)
- Normal-hearing children got about 3 dB SRM; children with hearing loss using bilateral aids showed none (Ching et al. 2011). — [Univ. of Manchester record](https://research.manchester.ac.uk/en/publications/spatial-release-from-masking-in-normal-hearing-children-and-child/)
- Bilateral aids gave better SRM than unilateral aids (Dawes and Munro); aids can distort level and timing cues. — [PMC5392088](https://pmc.ncbi.nlm.nih.gov/articles/PMC5392088)
- Binaural redundancy (summation) adds about 1 to 3 dB depending on masker. — [PMC5014088](https://pmc.ncbi.nlm.nih.gov/articles/PMC5014088)
- Hearing-impaired listeners' reduced SRM is consistent with increased energetic masking (Best et al.). — [PMC3689785](https://pmc.ncbi.nlm.nih.gov/articles/PMC3689785)
- Different listener groups need different minimum angular separations to get any SRM (Srinivasan, Jakien and Gallun). — [Proceedings ISAAR 2013 / related](https://proceedings.isaar.eu/index.php/isaarproc/article/download/2013-45/112)

### Inferences
- The head shadow component of SRM (several dB) is "free" and comes from where the target and noise sit relative to the head, not from the device. A passive horn can only scale the level on its side; it cannot create binaural cues.
- For a unilateral horn, the worst case is a talker on the unaided side with noise on the aided side: the horn then boosts the noise relative to the talker. A scene set should include this asymmetric case.

### Gaps
- No study found that measured SRM with a passive (acoustic) aid.

## Q7. Public datasets and cheap models for angle-dependent filtering; what is feasible in a weekend

### Takeaway
The cheapest credible approach is (1) the Brown and Duda spherical-head shadow filter for azimuth dependence, or (2) a measured KEMAR/HRTF dataset applied as a filter before the horn model. Full BEM (Mesh2HRTF) of a head plus horn is too slow for many designs in a weekend.

### Cited Findings
- Brown and Duda (1998), "A Structural Model for Binaural Sound Synthesis," IEEE Trans. Speech Audio Process. 6(5):476-488: starts from Rayleigh's spherical-head solution for head shadow, uses a simple first-order head-shadow filter plus delay, and models the pinna as a set of discrete echoes (amplitude plus delay). Shoulder cues were weak and dropped. — [eScholarship PDF](https://escholarship.org/content/qt0cr9d23p/qt0cr9d23p_noSplash_c6f0ae8be6c4003ba4f479c6ef3d369b.pdf); [dblp](https://dblp.uni-trier.de/rec/journals/taslp/BrownD98.html)
- In the Brown and Duda pinna model, relative echo timing mattered more than amplitude or spectra (1997 abstract). — [auditory.org ASA 1997 abstract](https://auditory.org/asamtgs/asa97pen/2pPP/2pPP15.html)
- Mixed structural modelling (Geronazzo, Spagnol, Avanzini) generalises the Brown and Duda approach. — [Geronazzo et al. DSP 2013](https://avanzini.di.unimi.it/downloads/publications/geronazzo_dsp13.pdf)
- BEM runtime: full audible-range HRTF calculation can still take tens of hours on one CPU; older reciprocal BEM runs took about 28 h per frequency for a 22,000-element mesh to 5.4 kHz, 9.15 h per frequency for a 30,570-element mesh to 10.3 kHz. Mesh grading cuts elements to about 10% and speeds it greatly. — [Ziegelwanger et al., a-priori mesh grading, arXiv 1606.00278](https://ar5iv.arxiv.org/html/1606.00278)
- Mesh2HRTF uses the fast multipole BEM; the SONICOM extended dataset computed HRTFs from 0 to 24 kHz in 150 Hz steps for 793 directions using graded meshes. Wall-clock time was not reported in the snippet. — [SONICOM extended dataset, arXiv 2507.05053](https://arxiv.org/pdf/2507.05053); [UMD fast multipole BEM HRTF](https://lccd.umiacs.umd.edu/node/14012)
- Shaw's numerical-form table (15-degree azimuth steps, 43 frequencies) is directly usable as an angle-dependent gain table. — [Scilit](https://scilit.com/publications/282faeae31950eea1af13ea3d0bb0556)

### Inferences
- Unverified (recall of Brown and Duda 1998 equations): head-shadow filter H(w, theta) = (1 + j*alpha(theta)*w/(2*w0)) / (1 + j*w/(2*w0)), with w0 = c/a, head radius a about 8.75 cm, alpha(theta) = (1 + alpha_min/2) + (1 - alpha_min/2)*cos(theta/theta_min * 180 deg), alpha_min = 0.1, theta_min = 150 deg. It gives about +6 dB at high frequency for a source facing the ear and about -20 dB in the deepest shadow. It is a few lines of code and runs instantly. Check against the eScholarship PDF before use.
- Datasets the user listed (MIT KEMAR, CIPIC, SADIE, HUTUBS) are standard free HRTF sets; none were fetched here, so their grids and licences are unconfirmed. They provide open-ear HRTFs only, so they model the angle-dependent field at the ear entrance, not the horn's effect.
- Weekend-feasible pipeline: angle -> (spherical-head filter or measured HRTF at the ear entrance) -> horn transfer function from a 1D horn/transmission-line model (Webster horn equation) -> ear canal. This separates angle (fixed, cheap) from horn optimization (the expensive inner loop). Full 3D BEM of head plus horn per design per angle is not realistic in a weekend.
- If 3D simulation is already in use for the horn, a single plane wave from each of the 5 angles on a coarse head/pinna mesh up to about 8 kHz is the most that is realistic, and only for the final design, not inside the optimizer.

### Gaps
- Mesh2HRTF wall-clock times on a modern laptop for a graded mesh were not found.
- CIPIC, SADIE, HUTUBS and MIT KEMAR details (subject counts, angle grids) were not verified in this session.

## Q8. Bottom line: is angle first-order or second-order for a passive in-concha horn's speech benefit? Which angles matter?

### Takeaway
Angle is first-order for the absolute level reaching the horn (head shadow changes high-frequency level by up to about 15 dB), but second-order for the horn's own insertion gain, because a concha-sized horn is nearly omnidirectional in the speech band. The cheapest credible plan is to optimize the horn at 0 degrees (front) against the OPEN-EAR baseline, then check a few angles with a head-shadow filter, especially the aided-side (90) and far-side (270) cases.

### Cited Findings
- Head-induced level differences of up to about 15 dB relative to front were measured at 45 and 120 degrees. — [Jensen et al. 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)
- Most of the roughly 10 dB spatial benefit for speech comes from head shadow; binaural timing gives about 2 to 3 dB. — [Shinn-Cunningham et al. 2001, citing Bronkhorst 2000](https://www.cmu.edu/dietrich/psychology/shinn/publications/pdfs/2001/2001jasa_shinn.pdf)
- Directivity differences between mic locations on a real head are about 1 to 3 dB. — [Dittberner and Bentler 2003](https://hearingreview.com/practice-building/practice-management/interpreting-the-directivity-index-di); [US patent 6704423](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6704423)
- In-concha placement mainly helps front-back localization (about 22 degrees less RMS error) with only about 1 dB speech-in-noise effect. — [Jensen et al. 2013](https://pmc.ncbi.nlm.nih.gov/articles/PMC4070616)
- The open ear already provides about 15 to 20 dB of natural gain near 2.7 kHz, which a concha device can remove. — [AudiologyOnline](https://www.audiologyonline.com/articles/common-clinical-encounters-59-but-909)

### Inferences
- Ranking of effect sizes for this device:
  1. Insertion loss vs open ear (losing up to about 15 to 20 dB of natural resonance gain if the canal or concha is blocked) — first-order, angle-independent.
  2. Head shadow on the aided ear (up to about 10 to 15 dB at 2 to 8 kHz between near-side and far-side talkers) — first-order for audibility, but the same with or without the horn.
  3. Horn directivity and pinna-cue preservation (about 0 to 2 dB in the speech band) — second-order.
- Angles that matter: 0 degrees (face-to-face conversation; design target), 90 degrees on the aided side (best case, slight extra level), 270 degrees or the far side (worst case; the talker is head-shadowed and the horn cannot help), 180 degrees (behind; pinna shadow of a few dB above about 1 kHz, mainly a localization issue). 45 degrees adds little information beyond 0 and 90.
- Because the horn's effect is close to angle-independent, a credible minimal test is: horn insertion gain at 0 degrees, plus one noise-at-side scene (target 0, noise 90 or 270) to show the asymmetric unilateral case. A five-angle sweep is useful for a demo but adds little to the design choice.
- Rotating the speaker in a full 3D simulation mostly reproduces known head-shadow numbers. Applying a Shaw table or Brown and Duda filter to the 0-degree horn result gives nearly the same answer at a tiny fraction of the cost. The exception is if the horn mouth is large (over about 4 cm) or protrudes from the concha, where its own directivity starts to matter above about 3 kHz.

### Gaps
- No direct measurement exists (that was found) of a passive concha horn's response vs source angle, so the claim that horn directivity is second-order rests on aperture physics and on the small directivity differences between omni hearing-aid mic locations.
- How much the horn alters the pinna's own direction-dependent filtering is unknown without a 3D simulation or a KEMAR measurement.
