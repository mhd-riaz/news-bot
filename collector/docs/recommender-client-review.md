# AFTERLINE: plain-English progress checklist

**Project-record review date:** 25 November 2026

**Audience:** readers with basic computer knowledge; no machine-learning background needed

## Project progress checklist

**A working news-reading demo has been built, but the complete private web service is not finished.**
The news collector is recorded as running on the owner's home computer.
The updated reading demo was last demonstrated on 24 November. Neither statement is a new check that the services are running today.

AFTERLINE gathers news and suggests what to read. The first release, called **V1**, is a website for about five invited people, not a public sign-up service.
**V2** is the later audio and iPhone version. The website must be useful without paying for an outside service.

This checklist summarises the [project roadmap](roadmap.md), [recorded results](recommender-results.md) and the latest detailed task entries.
It is a review of those records, not a new inspection of the live service.
Where an older summary disagrees with a later detailed entry or owner decision, the later record is used.
The technical review at the end is historical, not a second current task list.

**Dates:** the original V1 target was **15 November 2026**, which has passed.
The records do not show full release acceptance or an approved replacement date.
This checklist does not change the deadline, reduce the scope or close a release gate.

### How to read the tables

| Mark and status | Meaning |
| --- | --- |
| `[x] Done` | There is recorded evidence for the result described. Read the limit: done on one computer or done in code does not mean available in the live service. |
| `[~] In progress` | Part of the work is done, but an action, check or approval remains. This includes work waiting on someone else. |
| `[ ] Yet to do` | There is no recorded completion of this planned work. This does not prove that nobody has started it. |

A **classifier** sorts news into topics. A **recommender** suggests what someone might want to read.
Finishing a classifier does not finish the news website or prove that its reading suggestions are useful.
**Machine learning** means finding patterns in examples. A trained **model** is a program that has learned those patterns.

### What is done

| Check | Completed work | What the evidence does, and does not, show | Record |
| --- | --- | --- | --- |
| `[x] Done` | The news-collection foundation | The collector and its database are recorded as running on the home computer. The whole reader service has not passed the final always-on checks. | [R8-R9](roadmap.md#2-requirements) |
| `[x] Done` | A working news-reading demo | On 22 November, a separate local archive with 20,000 articles from 53 publishers was built and displayed. All three reading methods returned real articles. This was not a live-service release. | [LOCAL.1](roadmap.md#4-milestones) |
| `[x] Done` | Three ways to find related articles | Word matching and two learned methods are available in the demo. Word matching remains the default based on the earlier comparisons; the new archive has no new human-quality result. | [Earlier comparisons](recommender-results.md), [LOCAL.1](roadmap.md#4-milestones) |
| `[x] Done` | Reading controls and the redesigned reading space | The current local demo has a grid front page, a full-screen reading view, related-story tiles, interest selection, like/dislike controls and a light/dark switch. Likes do not reshuffle the open page: the reader chooses when to update it. Choices are browser-local, not a signed-in account. | [DEMO.4](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance) |
| `[x] Done` | Code to improve article information | Tested code cleans text, detects language, records where dates came from and tracks article changes. Completing the work on the live archive is still pending. | [M1.1-M1.4](roadmap.md#4-milestones) |
| `[x] Done` | More news sources prepared | Source settings and 25 added feeds were tested on a separate database. The additions are done in code, not confirmed as deployed to the live service. | [M1.6-M1.7](roadmap.md#4-milestones) |
| `[x] Done` | Basic database access and memory settings | Access checks passed on a test database; the owner confirmed live account setup. Memory limits are configured for the services already deployed. This is not a full security or capacity sign-off. | [M0.6-M0.7](roadmap.md#4-milestones) |
| `[x] Done` | A fair way to choose the final reading tests | The procedure for selecting 50 test cases is implemented and tested. The actual final reader study still needs to happen. | [M0.4](roadmap.md#4-milestones) |
| `[x] Done` | One unreliable automated test fixed | The timing-related test fix has recorded repeat-run evidence. Other testing work in the same milestone remains. | [M9.1 work log](roadmap.md#9-work-log) |
| `[x] Done` | A newer topic-classifier candidate trained locally | A separate candidate was trained using 8,594 artificial-intelligence-generated labels (AI labels). It has not been approved by human testing or put into the live service. It is not the reading demo's recommender. | [ML4.6 and its correction](roadmap.md#4-milestones) |
| `[x] Done` | A fresh-news demo for the 25 November review | On 24 November the reader gained Fresh, Yesterday and Archive views, a professional-news switch, and saved stories with notes. It ran on news collected that day. It runs on one laptop and keeps choices and notes in that browser only; it is not the hosted, signed-in service. | [DEMO tasks](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance) |

### What is in progress

| Check | Work in progress | What still needs to happen | Record |
| --- | --- | --- | --- |
| `[~] In progress` | Moving this project into the live service safely | Ready-to-run software packages can be built on one computer, but publishing the main package is blocked by its connection to the older project. Complete the safe handover and prove that the packages reach and run on the live computer. | [M0.5](roadmap.md#4-milestones), [18 November decision](roadmap.md#8-decision-log) |
| `[~] In progress` | Arranging the human reading review | The scoring rules were approved. Confirm the testers and their available review times; the original November grading dates have passed. | [M0.2](roadmap.md#4-milestones) |
| `[~] In progress` | Updating old articles with the new information | The update program is built and tested. Run it on the live archive after the approved deployment, check the results and confirm news collection was not interrupted. | [M1.5](roadmap.md#4-milestones) |
| `[~] In progress` | Finishing automatic website checks | The unreliable-test fix is done, and the 24 November demo added browser regression tests. The full browser-coverage and hardening targets still have no recorded acceptance. | [M9.1](roadmap.md#4-milestones), [DEMO.4](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance) |
| `[~] In progress` | Completing and reviewing the newer classifier work | The owner approved the V4 classifier for production on 27 November (D19) and the repository is prepared to serve it; deployment is not confirmed until its model file is on the production volume. Human validation remains **not met**: the 22 November correction says all old and new classifier labels were AI-generated, including ones earlier called human labels, so scores measure agreement with AI labels. The target of 200 human-reviewed examples for each of 13 topics is **not met**. | [ML4 tasks](roadmap.md#4-milestones), [D16](roadmap.md#7-open-decisions-owner), [D19](roadmap.md#7-open-decisions-owner) |

### What is yet to be done for V1

The last column names the detailed tasks in the roadmap. These rows group related tasks; they are not estimates of equal-sized jobs.

| Check | Work still needed | What finished should look like | Record |
| --- | --- | --- | --- |
| `[ ] Yet to do` | Check article dates and live data quality | Report which publishers have trustworthy publication dates. Verify the live data has the required cleaned text and language information. Do not silently relax the date rules. | [M1.9, M1 exit](roadmap.md#4-milestones), [C1-C2](roadmap.md#3-contracts-v1) |
| `[ ] Yet to do` | Complete health checks, backups and recovery | Existing services have health endpoints; complete checks for the planned stack, make a daily encrypted backup on another device and prove that it can be restored. Sending alerts to the owner is deferred to V2, not a V1 delivery promise. | [M1.8](roadmap.md#4-milestones), [D2-D3](roadmap.md#7-open-decisions-owner) |
| `[ ] Yet to do` | Keep recommendations up to date automatically | Build the full searchable article list, add new and changed articles regularly, remove articles that no longer qualify and recover safely from failures. A bad update must leave the previous working list available. | [M2.1-M2.7](roadmap.md#4-milestones) |
| `[ ] Yet to do` | Prove the one-hour news target | Test delayed articles, changes, failures, restarts and recovery. Then measure continuously for 48 hours: no article accepted into the recommendation list may take over 60 minutes from collection to becoming recommendable. Measure changed articles separately too. | [M2.8-M2.9](roadmap.md#4-milestones), [C5](roadmap.md#c5-freshness-sla-r5) |
| `[ ] Yet to do` | Private Google sign-in and the hosted reader | Create the Google sign-in setup, allow only invited accounts, protect each person's data and deploy the reader with sign-in required. Testers must actually sign in and use it. | [M3.1, M3.3, M3.8-M3.9](roadmap.md#4-milestones), [D10](roadmap.md#7-open-decisions-owner) |
| `[ ] Yet to do` | Likes and settings that follow the reader | A professional-source filter already works locally. Store likes, dislikes, topics and publisher choices in the account; add local/city settings, reset, data download and deletion. Check that choices survive a browser reset and a device change. | [M3.2, M3.7-M3.8](roadmap.md#4-milestones) |
| `[ ] Yet to do` | Release-grade fresh feed and archive | The local demo already separates fresh English stories (verified dates, 0-30 days old) from the archive and labels unverified dates. Integrate this with automatic index updates, accounts and the hosted reader; demonstrate the release checks. | [M3.4](roadmap.md#4-milestones), [C2](roadmap.md#c2-freshness), [DEMO](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance) |
| `[ ] Yet to do` | Account-backed saved stories, saved topics and notes | Saved stories and notes already work in one browser and survive a snapshot change. Add saved topics and account storage so readers can find them on another device. | [M3.5](roadmap.md#4-milestones), [DEMO.4](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance) |
| `[ ] Yet to do` | Reader-added news feeds | Readers can add their own publishers' automatic article lists, see collection status and disable their feeds. Only the existing collector fetches them, using its safety checks. | [M3.6](roadmap.md#4-milestones) |
| `[ ] Yet to do` | Stored daily editions for each account | The demo already calculates up to ten Yesterday stories from its snapshot. Build and store each account's edition with the planned topic caps and stability, explain short editions and have testers review three consecutive editions. The demo does not meet those full requirements. | [M4.1-M4.5](roadmap.md#4-milestones), [DEMO](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance) |
| `[ ] Yet to do` | Topic discovery and genuine follow-up stories | Suggest relevant topics the reader has not chosen, explain the links, give topics clear names and connect stories to later developments and relevant older reading. People must judge whether the links make sense. Adding these rules must not make the practice reading scores worse. | [M5.1-M5.7](roadmap.md#4-milestones) |
| `[ ] Yet to do` | The planned improved recommendation model | Train and serve the new model, compare it fairly with the existing methods and prove that replacing a model is safe. Use practice cases for tuning, never the final test cases. | [M0.3, M6.1-M6.5](roadmap.md#4-milestones) |
| `[ ] Yet to do` | Safe, read-only access for AI assistants | Assistants can search and read using their own access keys. They cannot change records, start training or access a reader's private account data. Check rejected and revoked keys too. | [M7.1-M7.4](roadmap.md#4-milestones) |
| `[ ] Yet to do` | The final human reading test | Freeze the system and its suggested lists. All invited testers, at least two people, grade 50 reading cases without knowing which method made each suggestion. Report whether the target below was met. AI scores are not a replacement. | [M8.1-M8.3](roadmap.md#4-milestones) |
| `[ ] Yet to do` | Final safety, speed and release checks | Review sign-in, permissions and safe display of publisher text. Confirm content/image permissions and that images are stored only as links, not image files. Test several users together, rehearse recovery, enable weekly model updates after evaluation, update release documentation and run the release checklist. | [M9.2-M9.6](roadmap.md#4-milestones), [D5-D6](roadmap.md#7-open-decisions-owner) |

### The checks that decide whether the work passes

These are the main existing plan targets, not new or lowered targets. The detailed linked tasks also apply.
The owner must decide any change to a target, deadline or feature.

| Area | Required result in plain English | Current evidence |
| --- | --- | --- |
| News freshness | Over 48 straight hours, both the slowest new-article time and the time that 95 out of 100 articles stay within must be at most 60 minutes. Count every article accepted into the recommendation list. | Not yet demonstrated. See [M2 exit](roadmap.md#4-milestones). |
| Topic suggestions | People judge at least 70% sensible across 20 practice profiles. Every suggestion shows its reason. | Not yet demonstrated. See [C6](roadmap.md#c6-association-rules-r7-r23). |
| Follow-up stories | People judge at least 70% of follow-ups genuine across 30 sampled articles. Every follow-up points to a later development. | Not yet demonstrated. See [C6](roadmap.md#c6-association-rules-r7-r23). |
| Topic names | At least 80% of 30 sampled labels make sense, and every topic has a label. | Not yet demonstrated. See [C6](roadmap.md#c6-association-rules-r7-r23). |
| Reading usefulness | Across the final 50 cases, at least 65% of the top-five suggestions must be rated useful, and the chosen method must not do worse than word matching. The small earlier pilot does not pass this final test. | Full human acceptance is unverified. See [C13](roadmap.md#c13-evaluation-r15) and [earlier results](recommender-results.md). |
| Several people using it together | The owner confirms the test load. The current default target is five readers plus two AI assistants, with 95 out of 100 responses taking no more than half a second. | This load has not been demonstrated. Earlier one-reader speed tests do not count. See [D5](roadmap.md#7-open-decisions-owner). |
| Release readiness | All required services run with healthy checks for 24 hours; recovery was rehearsed within the last 48 hours; release tests pass; requirements and unmet targets are honestly recorded. | The [V1 release checklist](roadmap.md#41-v1-release-checklist) is still unchecked. |

**If a target is missed, write "not met".**
Keeping the best available reading method as a fallback does not turn a failed target into a pass.
Do not treat AI-generated classifier labels as human-checked answers, or classifier scores as proof of useful recommendations.

### What belongs to later versions

These are planned ideas, not completed features or promises for V1.
V2 has not yet been designed in detail.

| Check | Later work | Meaning | Record |
| --- | --- | --- | --- |
| `[ ] Yet to do - V2` | Choose a listening time | Ask how many minutes the listener has. | [V2-1](roadmap.md#2-requirements) |
| `[ ] Yet to do - V2` | A briefing that fits that time | Turn the stored daily edition into one ordered spoken script of the right length. | [V2-2](roadmap.md#2-requirements) |
| `[ ] Yet to do - V2` | Spoken narration | Read the briefing aloud. | [V2-3](roadmap.md#2-requirements) |
| `[ ] Yet to do - V2` | Voice controls | Accept spoken playback, save and topic-exploration commands. | [V2-4](roadmap.md#2-requirements) |
| `[ ] Yet to do - V2` | iPhone app | Bring editions, audio, saved items and notes to an app. | [V2-5](roadmap.md#2-requirements) |
| `[ ] Yet to do - V2` | Assistant access to personal saved items | Decide and build safe access to a reader's own saved stories and notes. V1 assistants do not get this access. | [V2-6](roadmap.md#2-requirements) |
| `[ ] Yet to do - V2` | Deliver alerts to the owner | Choose an alert channel and add delivery; this was deferred from V1. | [D3](roadmap.md#7-open-decisions-owner) |
| `[ ] Yet to do - after V2` | Android app | Build the Android version after V2. | [L-1](roadmap.md#2-requirements) |

### The 25 November demo

**What it shows:** today's news first, a short "yesterday" selection, news limited to AI, software and data-science sources, older background behind today's stories, and saved stories with notes. It runs on the owner's laptop, and likes, settings and notes stay in that browser.

**Before the demo** (from `collector/`; allow time for a rebuild, and leave the local collector running):

1. `make rec-inspect` must show the intended local database. `make demo-refresh` then takes a new recent-first snapshot and fits all three reading methods; elapsed time depends on the machine and corpus.
2. Stop the old ranker, then run `make demo-serve`.
3. In a second terminal, run `make reader`, then open http://127.0.0.1:8090/stories in a private browser window, so the demo starts with no likes, settings or saved stories from rehearsals. It starts in the computer's light or dark setting.

**Suggested walk-through:**

1. **Fresh** opens on a grid of the newest stories with a verified publication date: one large lead story, then rows of three. The snapshot time is under "The collection", at the bottom of the page.
2. Tick **Professional focus**: only AI, software, data-science and technology sources remain.
3. **Choose interests**: pick two or three of today's stories. The page title changes to "For you".
4. Open a story: it reads full screen, like a magazine page. At the end, **Related reading** shows six related stories, each marked "Fresh" or "From the archive"; **See all related stories** opens the full set. Whether older archive stories appear depends on the story, so pick one in rehearsal that has older background.
5. **Save** a story (☆ on any tile, or **Save** inside the story) and type a note, then open **Saved stories** to show it.
6. Switch to **Yesterday**: up to ten stories from yesterday, in India time, ranked by the chosen interests.
7. Optional: switch the lens between TF–IDF, SVD and Neural, or press **Dark theme** at the top right.

The morning refresh and rehearsal ([DEMO.6](roadmap.md#demo--bare-minimum-client-demo-separate-from-release-acceptance))
still have no recorded completion. The walkthrough above is a script, not evidence that
the 25 November rehearsal has happened.

**What not to claim:** this is not the hosted service and has no sign-in. Choices live in one browser. The snapshot is refreshed by hand, so the one-hour freshness target is not shown. Topic suggestions, follow-up stories, assistant access and the human reading test are not built yet. The earlier reading-quality numbers come from a small pilot and do not meet the final target.

### Keeping this checklist accurate

Change a row to **Done** only when its linked task has recorded evidence.
Keep the scope visible: code written, local demo, live deployment and human acceptance are different results.
Update the roadmap first, then this summary. Do not calculate a completion percentage from these rows: the jobs differ greatly in size.

## Historical technical review

<details>
<summary>Open the earlier client and architecture review (23 October 2026)</summary>

The review below describes the original `stories-002` demonstration.
It is retained as historical evidence, not the current release status or a list of decisions still awaiting approval.
Later roadmap decisions and the checklist above take precedence.
The separate local archives built on 22 and 24 November do not replace or revalidate its measurements.

**Original review date:** 23 October 2026

**Audience:** client stakeholders, solution architect and engineering reviewers  
**Delivered edition:** `stories-002`  
**Current application-code checkpoint inspected:** `c06fdf4`  
**Maturity:** working, integrated MVP for pilot review; not production acceptance

## 1. Executive summary

We extended an existing news-collection and topic-classification project into a **content-based news archive recommendation system** with a focused, Stories-inspired reading interface.

The system works with real MongoDB articles, not a demonstration fixture. It recommends related articles and adapts to articles a reader explicitly selects. It includes three comparable retrieval methods: TF-IDF, SVD and a locally trained TensorFlow/Keras autoencoder.

**TF-IDF is the current reading default because it led the available relevance comparisons.** The neural model remains trained, integrated and selectable; its learned representations also support the content clusters used for exploration.

The main engineering outcomes are:

- An end-to-end path from existing MongoDB data to trained representations, recommendation APIs and the reader.
- A versioned, reproducible 20,000-article edition with original records preserved.
- A genuinely trained unsupervised neural representation model, alongside simpler controls.
- Explicit feedback, cold start, duplicate/history exclusions and honest archive presentation.
- Measured local retrieval performance, automated tests, browser checks and a verified private backup.

The main qualification is equally important: **technical integration is demonstrated, but full human-validated recommendation quality is not yet signed off.** The broader relevance assessment is AI-assisted and is kept separate from the small human pilot.

## 2. Business problem and intended value

The previous project answered: "Which topic does this article belong to?"

The new project answers:

1. "What should I read next after this article?"
2. "What articles match the interests I have selected?"
3. "Where can a new reader start without an existing profile?"

The intended value is easier discovery and reuse of an existing archive through a calmer, focused reading experience. Improvements in engagement, retention or business conversion have **not** been measured and are not claimed.

### What this is not

It is not a live breaking-news service, social network, generative news writer, fact-checking system or collaborative recommender trained on historical reader behavior.

## 3. What was reused, changed and built

| Area | Existing foundation reused | New or modified work |
| --- | --- | --- |
| News acquisition | Go RSS/Atom collector and article enrichment | Collection logic preserved; not started by the new reader |
| Data | Existing MongoDB `news` corpus and stable article IDs | Read-only export, language checks and frozen recommendation edition |
| Preparation | Existing text cleaning, boilerplate discovery and admission patterns | Consistent recommendation input and bounded cohort preparation |
| Duplicate handling | Existing identity/hash concepts and recurring-template guard | Conservative story grouping and result exclusions |
| ML tooling | Python, scikit-learn, NumPy, SciPy, PyArrow and existing project packaging | TF-IDF retrieval, SVD control, TensorFlow autoencoder and learned content clusters |
| API infrastructure | Go HTTP/service/repository patterns and Flask serving conventions | Recommendation service, metadata contract and one-query article hydration |
| Reader | Go templates, native CSS and plain JavaScript | AFTERLINE story interface, onboarding, feedback, local profile and navigation |
| Reliability | Existing health, logging, authentication and configuration patterns | Read-only entry point, dependency readiness and native idle-connection retirement |
| Delivery | Existing test runners and build tools | Recommendation tests, evaluation artifacts, review documentation and verified backup |

The original supervised topic classifier is preserved. Its classification scores are not reused as evidence of recommendation quality, and its category labels do not train the new unsupervised model.

## 4. Dataset actually used

The live database can grow independently of the delivered index. The edition, rather than today's changing database count, is the reproducibility boundary.

| Measure | Delivered edition |
| --- | ---: |
| Original records scanned before cutoff | 165,624 |
| Collection cutoff | 22 October 2026, 18:00 UTC |
| Seeded reservoir candidates | 30,000 |
| Prepared/indexed articles | 20,000 |
| Publishers represented | 40 |
| Body-backed model inputs | 19,391 |
| Summary-backed model inputs | 494 |
| Headline-only model inputs | 115 |
| Stored images available | 12,237 |
| Conservative story groups | 19,967 |
| Representation training / validation | 16,000 / 4,000 |

Stored publication dates span October 2007 to October 2026. The UI therefore presents the collection as an archive, with absolute dates, not as today's news.

### Data issues addressed

- Some records marked `language=en` actually contained Hindi or other non-English text. Preparation checks the text instead of trusting that metadata.
- Articles have different amounts of available content. All methods use the same fallback recipe.
- Publisher furniture, repeated leads and encoding problems can pollute text features. Existing cleaning is reused, but it is not assumed to solve every extraction problem.
- A non-empty body does not certify a complete publisher article.
- Some publication dates were substituted from collection time by the original collector. Equality is conservatively labelled "Collected"; publisher-date provenance is not uniformly verified.
- Identical titles are not automatically duplicates: recurring features can reuse a headline.

A connection mismatch was also detected: the initial local endpoint contained a smaller August-only archive. The correct larger database was configured and verified before building the final edition.

## 5. Architecture

### C4 level 1: system context

```text
[Reader / browser] ----> [AFTERLINE recommendation system]
                               |
                               +---- reads ----> [Existing news MongoDB]

[Reader / browser] ---- images / original links ----> [Publisher sites and CDNs]
```

The original collector remains an independent producer of the MongoDB corpus. The recommendation reader is a consumer, not a replacement collector.

### C4 level 2: runtime containers and data stores

```text
OFFLINE
[Existing MongoDB]
       |
       v
[Python preparation and training CLI]
       |
       v
[Versioned local artifacts: snapshot, models, matrices, clusters, hashes]

ONLINE
[Browser: Go-rendered HTML + CSS + JavaScript]
       |
       v
[Go read-only reader / API :8090] ---- batch article reads ----> [Existing MongoDB]
       |
       +---- private HTTP ----> [Python Flask/Gunicorn ranker :8001]
                                      |
                                      +---- reads ----> [Versioned artifacts]
```

These are separate processes and responsibilities. A browser request does not initiate training, scraping or a migration.

### Why this separation

- Go retains the existing application boundary and ownership of MongoDB access.
- Python retains the scientific/ML ecosystem and numerical retrieval.
- Heavy preparation happens offline.
- The online service reuses saved representations; it does not import TensorFlow to serve each recommendation.
- Same-origin browser APIs avoid an additional public ML API and cross-origin configuration.

There is no added vector database, cache cluster, message broker, frontend framework or external LLM dependency in the recommendation path.

## 6. Technology choices and rationale

| Technology | Role | Why it was selected |
| --- | --- | --- |
| Go 1.27+ | Reader, public API and MongoDB hydration | Reuses the existing backend and operational patterns |
| MongoDB | Original article source of truth | Reuses the existing dataset and article identifiers |
| Python 3.12 | Preparation, training and numerical retrieval | Fits the existing ML project |
| scikit-learn | TF-IDF, SVD, normalization and MiniBatchKMeans | Existing, focused implementations rather than custom algorithms |
| TensorFlow 2.21 / Keras 3.15.1 | Denoising autoencoder training | Delivers meaningful local neural learning within the project constraints |
| NumPy / SciPy | Dense/sparse representations and on-demand similarity | Adequate for the bounded cohort without another retrieval service |
| Flask / Gunicorn | Private representation service | Reuses the project's Python serving approach |
| Go templates / native CSS / JavaScript | Stories-inspired frontend | No new bundler, Node runtime or framework migration |
| pytest / Go tests / native Node tests | Verification | Extends existing tooling; Node is not needed to run the reader |

Training was demonstrated on the inspected Apple M1 Pro/32 GB machine using CPU. GPU acceleration is not a runtime requirement for this edition.

## 7. Offline preparation and training

The offline sequence is:

1. Select a past collection cutoff.
2. Scan MongoDB in stable ID order with bounded field projections and cursor batches.
3. Reservoir-sample candidate records with a fixed seed.
4. Clean title, summary and body separately.
5. Apply language and article-admission checks.
6. Assemble the consistent model input.
7. Freeze article IDs, prepared text, metadata and provenance.
8. Group known/exact and conservative near-duplicate stories.
9. Establish a chronological, story-group-aware training boundary.
10. Fit TF-IDF, SVD and scaling using training data only.
11. Train the autoencoder, produce centered/normalized vectors and build content clusters.
12. Persist all artifacts and verify their ID alignment and hashes.

### Input recipe

```text
Headline + first 250 cleaned body words
             |
             +-- no usable body: use cleaned stored summary
             |
             +-- neither available: headline only
```

The same recipe is used for all three comparison methods. Names, places and numbers remain useful article content. Category labels, source IDs, publisher names, URLs and image data are not model features.

The display recipe is separate: prefer a stored summary, otherwise show a clearly labelled excerpt or headline-only state. No generative summarization is used.

## 8. The three recommendation representations

| Method | Representation | Purpose |
| --- | --- | --- |
| TF-IDF | Sparse word unigrams/bigrams; vocabulary capped at 25,000 | Transparent non-neural baseline and current reading default |
| SVD | 256-dimensional latent semantic representation | Control for the benefit of dimensionality reduction alone |
| Neural | 64-dimensional autoencoder bottleneck | Locally learned nonlinear article representation |

### What the neural model actually learns

```text
256 standardized SVD features
  -> Gaussian noise, standard deviation 0.05
  -> Dense 128, GELU
  -> Dense 64, bottleneck
  -> Dense 128, GELU
  -> Dense 256, linear reconstruction
```

The network contains **82,496 parameters** and uses Adam with mean squared reconstruction error. Training includes batching, fixed seeds, deterministic CPU settings and validation-based early stopping. The delivered run used 30 epochs.

The input is its own clean reconstruction target. This is unsupervised learning, not classification or click prediction.

Recorded baseline preparation took 80.37 seconds; the recorded neural training/clustering stage took 7.85 seconds. The latter is not total export/preparation time.

Final validation reconstruction MSE was 0.4165. That value is an optimization diagnostic, not recommendation accuracy.

Eight MiniBatchKMeans groups over learned vectors support the topic circles and representative cold-start articles. Their labels are derived from real top terms and are not a verified editorial taxonomy.

## 9. How recommendation behavior works

### Related reading

The opened article is the positive query. Unrelated saved interests do not dilute that query.

### Interest-based reading

The selected positive article vectors are averaged and normalized into a content profile. Explicit negative choices adjust ranking:

```text
score(candidate)
  = cosine(candidate, positive profile)
    - 0.2 * cosine(candidate, negative profile)
```

The second term applies only when negative choices exist. This is a simple content adjustment, not a calibrated model of user preference.

### Cold start

Readers without interests can explore representative articles from learned content groups. The starting experience does not pretend to know their preferences or popularity trends.

### Exclusions and diversity

The retriever excludes the current article, selected interests, explicit negative items, supplied viewed history and their known duplicate groups. At most one item from a known duplicate group enters a result page.

A publisher cap encourages variety where candidates permit it. Only that cap is relaxed to fill a page; duplicate/history exclusions are not relaxed.

Duplicate detection is conservative, not a guarantee that all paraphrased copies are recognized. The current scoring also contains no freshness or breaking-news boost.

## 10. What happens during one online request

1. The browser sends a selected method, optional seed/interests, viewed IDs and result limit.
2. Go validates the bounded request and calls the private ranker.
3. Python validates IDs against the named edition.
4. The selected matrix produces on-demand similarity scores.
5. Exclusion, topic-group and publisher-diversity rules select article IDs.
6. Go hydrates those IDs in **one bounded MongoDB query**, avoiding per-result database requests.
7. Go preserves ranking order and returns original article metadata plus the labelled snapshot snippet and matching reason.
8. The browser renders fetched text as text, not executable HTML.

If records have disappeared from MongoDB, unavailable IDs are explicit. If all ranked articles are missing, the request fails rather than returning a fabricated successful feed.

Features and snippets are frozen to an edition; original metadata is read live. That distinction matters if an existing article changes after export.

## 11. Delivered reader experience

- Horizontal content-group circles and immediate archive exploration.
- Selection of a few real articles to initialize interests; onboarding can be skipped.
- Focused story cards with headline, short text, source, absolute date and original-source link.
- Real publisher imagery where available and an intentional text-first design otherwise.
- Interested and not-interested actions affecting subsequent retrieval.
- Previous/next controls, keyboard navigation and touch-pointer handling.
- Position/progress indicators without a countdown or forced advancement.
- Explicit loading, error/retry, unavailable-content, empty and exhausted-feed states.
- Method switching between TF-IDF, SVD and Neural.
- Local profile reset and visible storage-failure handling.
- A legacy archive reader retained as an alternative.

The viewer is not claimed to hold every complete original article. It presents the available summary/excerpt/headline honestly, with the original reporting one click away.

Profiles are browser-local and edition-specific: up to 50 positive choices, 50 negative choices and the last 2,000 viewed IDs. Previous navigation can revisit the loaded trail even though new retrieval excludes supplied history.

## 12. API contract and boundaries

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/recommendations/meta` | Edition, coverage, methods, default method and content groups |
| `POST /api/v1/recommendations` | Related, interest-based or exploratory recommendations |
| `GET /api/v1/articles` | Existing article listing |
| `GET /api/v1/articles/{id}` | Original stored article detail |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | MongoDB and ranking dependency readiness |
| `GET /stories` | AFTERLINE reader |
| `GET /archive` | Legacy reader |

Recommendation requests are limited to 30 results, 50 positive IDs, 50 negative IDs and 2,000 viewed IDs within a 128 KiB payload bound.

Responses identify the method and snapshot, matching reason, labelled text, exhaustion state and unavailable IDs. Invalid input returns 400; an unindexed seed/interest returns 404; service/database failures are surfaced as 503.

Similarity scores are not probabilities of liking, editorial confidence or factual reliability.

## 13. Evaluation: what the evidence says

Evaluation compared the same fixed 40 cases and indexed corpus across all methods: 30 related-article queries and ten explicit multi-interest profiles.

### Human pilot: two cases

The user graded 20 blinded candidate pairs:

| Method | Useful Precision@5 | Pooled nDCG@5 |
| --- | ---: | ---: |
| TF-IDF | 0.80 | 0.9349 |
| SVD | 0.70 | 0.6596 |
| Neural | 0.60 | 0.5755 |

This is a small pilot, not broad human validation.

### Separate AI-assisted assessment: all 40 cases

A user-approved blinded AI pass rated 437 candidate pairs without seeing methods, ranks, scores or prior human grades:

| Method | Useful Precision@5 | Pooled nDCG@5 |
| --- | ---: | ---: |
| TF-IDF | 0.565 | 0.8526 |
| SVD | 0.480 | 0.7375 |
| Neural | 0.380 | 0.6435 |

The AI exactly agreed with only eight of 20 overlapping user grades. Its assessment is a useful proxy, not validated human ground truth. It must not be merged into a human benchmark.

Precision@5 counts grade-2 useful recommendations among the first five. Pooled nDCG measures ordering against the best ordering inside the judged candidate pool; it is not exhaustive corpus relevance.

The neural model did not outperform the baseline. TF-IDF therefore became the conservative default rather than choosing a more complex method solely because it is neural.

**The original full human-quality acceptance target is still unverified.** The AI-assisted TF-IDF P@5 is itself below 0.60. No passing quality claim is made.

The 16,000/4,000 temporal split validates representation reconstruction, not reader satisfaction. The recommendation comparison is in-catalog; it does not establish out-of-time article quality, unseen-user preference prediction or online business outcomes.

## 14. Performance and scale

Three warm-ups and 100 measured requests per method exercised the Go/Python/Mongo path:

| Method | End-to-end p50 | End-to-end p95 |
| --- | ---: | ---: |
| TF-IDF | 12.55 ms | 15.12 ms |
| SVD | 11.37 ms | 12.92 ms |
| Neural | 11.13 ms | 14.07 ms |

All 309 requests passed the edition, hydration and exclusion checks. These measurements comfortably beat the proposed 500 ms warm local p95 target.

They are single-reader measurements on the inspected machine and configured database connection, not concurrent-load results, internet/mobile rendering times or a production SLA. Image downloads are excluded.

Twenty thousand 64-dimensional float32 vectors occupy roughly 5.1 MB. That is not total process memory: metadata, sparse features, SVD representations, runtime libraries and duplicated workers add overhead.

No complete article-by-article similarity matrix is saved. Runtime retrieval calculates one score per candidate and orders the bounded corpus. Offline duplicate comparison remains quadratic despite its bounded batches; full-corpus scaling is not certified.

## 15. Verification and operational resilience

Recorded delivery checks include:

- **199 Python tests passed**; recommender coverage 94%, ranking 99%, Flask API and CLI 100%.
- **18 native Node checks passed**; JavaScript coverage 58.19% lines and 90.23% branches.
- All 142 top-level tests in the changed Go surfaces passed; focused race and vet checks passed.
- Browser journeys covered real-data onboarding, feedback, related reading, method changes, keyboard navigation, mobile-width layout and text-first cards.
- Explicit temporary browser fixtures covered otherwise hard-to-reach missing-content, empty and outage states; those fixtures were not left in the integration.
- The final browser reload verified TF-IDF by default, continued Neural selection, no page errors and no horizontal overflow at 390 pixels.

The full-repository Go run also exposed an unchanged, scheduling-dependent rate-limit test failure. It is documented rather than hidden behind a blanket "all tests pass" statement.

Startup and Mongo wrapper unit coverage remain low; actual startup/hydration checks supplement but do not replace those coverage numbers. JavaScript line coverage is below the proposed 80% target.

### Connection and restart checks

The reader now retires idle Mongo data sockets after 60 seconds through the native driver policy. The setting is configurable; existing collector defaults remain unchanged.

A fresh reader, a real article join, the first read after 70 seconds idle, an intentional model-service stop and subsequent recovery were verified. A stopped ranker correctly produced 503 instead of a successful-looking substitute feed.

This mitigates the observed stale-connection condition. It does not guarantee availability through arbitrary database or network failures.

## 16. Security and data handling

Implemented controls include:

- A separate reader command with no migration, source-management, retention-delete, collection, enrichment, classification-worker or telemetry-write path.
- Bounded requests, typed IDs, parameter validation, explicit errors and bounded downstream calls.
- Escaped Go templates, text-only DOM assignment, a restrictive content policy and safe URL schemes.
- No server-side arbitrary-URL image proxy.
- Existing authentication integration and an optional private recommender API key.
- Environment-based secrets excluded from source and the handover archive.
- Trusted-local-artifact loading, with edition hashes and ID/matrix alignment checked at startup.

Important limits:

- The demonstrated configuration is loopback development with reader authentication disabled. It is not a publicly deployable security configuration.
- Read-only behavior is an application property; a dedicated read-only MongoDB role still needs to be enforced operationally for production.
- Browser-local preferences are sent to the recommendation endpoint but are not persisted as server-side user histories. Local storage is not an encrypted user vault.
- External images and original links contact publisher infrastructure. Referrer suppression does not anonymize the reader's IP address.
- There is no delivered tenant isolation, account-based article authorization or production identity integration.
- No independent penetration test, security certification or production threat-model sign-off is claimed.

## 17. Operations, reproducibility and backup

Preparation writes derived artifacts separately from MongoDB. The edition saves prepared text/IDs, cleaning settings, seed, split, vocabulary, preprocessing, both Keras models, representations, clusters, training history and hashes.

At briefing preparation, the saved corpus/model/retrieval hashes matched, live readiness returned HTTP 200, and the shared browser showed the 20,000-article edition using TF-IDF.

Local startup is:

```bash
# Terminal 1, from collector/
make rec-serve REC_ID=stories-002

# Terminal 2, from collector/
make reader
```

The existing Docker/Compose assets for the collector/classifier were preserved. A production deployment pipeline, scheduled index publication, rolling edition promotion and production observability stack for the new reader/ranker have not been delivered.

A private handover archive contains 246 files, approximately 121 MB, including source, the trained edition and separate evaluation records. Every member hash was checked. A restored copy loaded the copied model artifacts, passed model-service requests and compiled the Go reader.

That restoration reused installed dependencies; it was not a new-machine or new-OS installation certification. The archive excludes secrets, virtual environments and executables and still requires the original MongoDB connection. Copying it off the laptop and checking dataset redistribution rights remain operational responsibilities.

## 18. Decisions requested from the client and architect

| Decision / gate | Why it matters |
| --- | --- |
| Confirm archive discovery versus live-news requirements | A freshness policy and update pipeline are different scope |
| Approve the relevance rubric and independent human assessment | The current human pilot is too small; AI assessment is not acceptance |
| Confirm pilot audience, languages, topics and expected traffic | Determines data admission, editorial labelling and capacity needs |
| Approve hosting, authentication, TLS and database permissions | The current loopback demo is not public production deployment |
| Approve privacy, profile retention and content/image rights | Browser-local profiles and publisher assets have policy implications |
| Set edition update, rollback and recovery requirements | New articles are not automatically indexed |
| Define load, memory and availability acceptance tests | Warm single-reader latency is not a production SLA |
| Agree the quality-improvement evaluation protocol | Future tuning needs a development set and fresh held-out assessment |

## 19. Anticipated review questions

**Why content-based rather than collaborative filtering?**  
There is article content but no usable user-item interaction history. The existing event collection was empty and carried no user identifier. Explicit selections form a content profile; "readers like you" claims would be unsupported.

**Which parts are unsupervised, and why does that matter here?**  
SVD, autoencoder reconstruction and k-means grouping all learn structure without labelled targets. That matters commercially because the system needed no labelling programme and no historical behaviour data to start working.

**Where is the neural model actually used?**  
It is trained locally on 16,000 real articles as an 82,496-parameter encoder/decoder. Its saved 64-dimensional representations drive one selectable retrieval method and the content groups used for exploration.

**Why run SVD before the network?**  
It avoids densifying 25,000-dimensional sparse features and keeps CPU training tractable. SVD-only retrieval is retained as a control, so any neural gain can be attributed correctly.

**Why a denoising objective?**  
The encoder reconstructs clean features from mildly perturbed inputs, which encourages robustness. Whether that helps must still be judged through retrieval quality, not reconstruction loss.

**Why index 20,000 articles rather than the whole corpus?**  
A frozen cohort makes preparation, comparison and delivery within the agreed timeline tractable. Full-corpus indexing needs more efficient duplicate candidate blocking first; that is scoped work, not a hidden defect.

**How are articles with very little text handled?**  
They use the same preprocessing with no invented supporting text. Headline-only items are a known weaker slice and are reported separately rather than averaged away.

**How do you avoid evaluation leakage?**  
Story grouping and chronological splits separate representation fitting from validation. Category and relevance labels never train the unsupervised model, and the earlier classifier's held-out set stays closed.

**How is recommendation quality measured?**  
Same-case Precision@5 and pooled nDCG, with human and AI-assisted label sources reported separately, plus latency, diversity and functional checks.

**Does lower training loss mean better recommendations?**  
No. Reconstruction optimises an input-copying objective, not reader usefulness. The two are reported separately for exactly this reason.

**TF-IDF beat the neural model — was the ML work wasted?**  
No. The comparison is the result. We use the simpler method for reading, retain the trained model as a measured option, and reuse its representations for content grouping. Choosing the more complex method without evidence would have been the worse outcome.

**What are the main limitations?**  
Small human judgement coverage, AI-assessment bias, English-language and publisher imbalance, imperfect duplicate and date handling, browser-local history, archive-only indexing and dependency availability.

## 20. Recommended review demonstration

1. Show edition coverage and archive dates.
2. Explore a content circle without an existing profile.
3. Select a few actual articles as interests.
4. Demonstrate interested/not-interested behavior and related reading.
5. Switch TF-IDF, SVD and Neural without changing the underlying cohort.
6. Show the text-first fallback, original-source link, keyboard navigation and profile reset.
7. Explain the offline/online separation and the absence of Mongo writes.
8. Present human and AI evaluation tables separately, followed by latency and known limitations.

### Suggested closing statement

> We have delivered a working, evidence-backed recommendation MVP on the existing news infrastructure. It includes a genuinely trained neural representation model, but the simpler TF-IDF method is the current reading default because it performed better in the available comparisons. The system is ready for a controlled pilot and architectural review. Production deployment and full human relevance acceptance remain explicit next gates rather than assumptions.

## 21. Supporting evidence and code entry points

- [Measured results and verification caveats](recommender-results.md)
- [Setup, training, evaluation and API instructions](recommender.md)
- [Read-only Go entry point](../cmd/reader/main.go)
- [Go recommendation orchestration](../internal/recommendation/recommendation.go)
- [Public recommendation handlers](../internal/handler/recommendation.go)
- [Dataset preparation](../ml-v2/src/newsrec/data.py)
- [Baseline and neural training](../ml-v2/src/newsrec/model.py)
- [Ranking and exclusions](../ml-v2/src/newsrec/index.py)
- [Private model API](../ml-v2/src/newsrec/api.py)
- [Evaluation and provenance enforcement](../ml-v2/src/newsrec/evaluate.py)
- [Story markup](../internal/web/templates/stories.html), [styling](../internal/web/static/stories.css) and [browser behavior](../internal/web/static/stories.js)
- [JavaScript regression checks](../scripts/stories.test.mjs)

</details>
