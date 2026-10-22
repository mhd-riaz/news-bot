# Labelling guide

Taxonomy version 4. Generated from `ml/taxonomy.yaml` — do not edit by hand.

Fill the **`label`** column with exactly one id from the table below.
Leave `notes` for anything that felt wrong; it is read, not ignored.

## How to choose

Pick the one class the article is most about from the table below. The list is fixed —
13 classes, one level, no finer subdivision beneath any of them — so every article gets
exactly one id and there is no group-vs-specific judgement call to make.

## Rules

1. Label what the article is **about**, not where it happened. A Karnataka election story is `politics`, not a geography.
2. If it fits none of them, or you genuinely cannot tell, write `unsorted`. A forced guess is worse than an honest blank — it becomes silent noise no one can find later.
3. Judge only from the title and summary shown. Do not search for the article. That is what the model sees, so that is what the label has to be based on.
4. Pick the **dominant** subject when two apply, and say so in `notes`.
5. Format is not subject. An opinion piece about cricket is still `sport`.
6. The political process beats its subject. A legislature, ministry, regulator or party acting is `politics`, even when the subject is the environment, defence or technology.
7. An attack or military operation is `conflict_war`; prosecuting one in court is `crime_justice`; a minister's remarks about one are `politics`.

## Classes

| id | covers | does not cover |
| --- | --- | --- |
| `politics` | Government, elections, diplomacy, campaigns, protest and activism, and public administration — legislation, ministries, budgets, regulation, candidates, polling, foreign relations, treaties, state visits, and demonstrations or civil dissent are all one class. | A crime prosecuted in court, which is crime_justice. Armed conflict, which is conflict_war. |
| `crime_justice` | Crime, policing and the legal system — criminal acts, investigations, arrests and fraud reported as an offence, plus trials, verdicts, sentencing and the judiciary as an institution. | Legislation being debated, which is politics. |
| `business_economy` | Companies, markets and the economy — corporate results, mergers, executives, layoffs and strategy; stocks, currencies, commodities, bonds, investing and public offerings; GDP, inflation, employment, trade, taxation and central banks. | A tech company's product launch, which is technology. |
| `technology` | Computing, the internet, devices and the technology industry — artificial intelligence and machine learning; cybersecurity, breaches and privacy; consumer gadgets, apps and product launches; and technology companies as businesses, startups, chips and platforms. | Government regulation of tech, which is politics. Research findings, which is science_space. |
| `science_space` | Scientific research and spaceflight — physics, biology, chemistry, archaeology, palaeontology and discovery, plus astronomy, space missions, satellites and rockets. | Medical and public-health research, which is health. |
| `entertainment_arts` | Entertainment, the arts and cultural life — film, television, streaming, music, celebrity and the media industry, plus books, visual art, theatre, dance, design and heritage. | — |
| `society_lifestyle` | Society, work and daily life — human interest, religion, festivals, migration, communities and social issues; unions, strikes, wages, hiring and workplace rights; travel, food, fashion, relationships, wellbeing, homes and hobbies. | — |
| `health` | Medicine, disease, public health, hospitals, mental health, nutrition and drugs. | Health insurance markets, which is business_economy. |
| `education` | Schools, universities, exams, admissions, curriculum, teachers and students. | — |
| `environment_climate` | Climate change, pollution, conservation, wildlife, the energy transition and natural resources. | A natural disaster as it happens, which is disaster_accident. |
| `disaster_accident` | Earthquakes, floods, storms, fires, industrial and transport accidents, and the emergency response to them. | The long-run climate context, which is environment_climate. |
| `conflict_war` | Armed conflict, military operations, terrorism, insurgency, peace talks and their humanitarian consequences. | Defence procurement debated in parliament, which is politics. |
| `sport` | Matches, tournaments, players, teams, transfers, doping and the bodies that govern sport. | — |
| `unsorted` | Anything else, or genuinely unclear. | — |

## Why some rows repeat across sheets

40 articles appear in every sheet on purpose. Comparing how differently two people labelled the same article is what tells us whether the classes are well defined. Do not coordinate on them.

## Returning the sheet

Keep the `article_id` column exactly as it is — it is how labels are matched back.
Do not add, remove or reorder rows. Save as CSV, keeping UTF-8 encoding.
