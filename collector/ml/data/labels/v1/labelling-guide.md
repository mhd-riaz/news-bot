# Labelling guide

Taxonomy version 3. Generated from `ml/taxonomy.yaml` — do not edit by hand.

Fill the **`label`** column with exactly one id from the table below.
Leave `notes` for anything that felt wrong; it is read, not ignored.

## How to choose

The classes come in two levels. Work in two steps:

1. Pick the **group** the article belongs to — the bold rows.
2. Pick the **specific class** inside that group — the indented rows.

**Always give the specific class.** A bare group label is a fallback for the rare
article that genuinely spans two of its children: "Prime minister campaigns while
on a state visit" is both diplomacy and elections, so it is `politics`. If you find
yourself reaching for group labels often, something is wrong with this guide — say so.

Groups with no indented rows beneath them are used as they are.

## Rules

1. Label what the article is **about**, not where it happened. A Karnataka election story is `politics_elections`, not a geography.
2. If it fits none of them, or you genuinely cannot tell, write `unsorted`. A forced guess is worse than an honest blank — it becomes silent noise no one can find later.
3. Judge only from the title and summary shown. Do not search for the article. That is what the model sees, so that is what the label has to be based on.
4. Pick the **dominant** subject when two apply, and say so in `notes`.
5. Format is not subject. An opinion piece about cricket is still `sport`.

## Classes

| id | covers | does not cover |
| --- | --- | --- |
| **`politics`** *(fallback — only if two below apply equally)* | Government, elections, diplomacy, parties and public administration. | A crime prosecuted in court, which is crime_justice. Armed conflict, which is conflict_war. |
| ↳ `politics_government` | Legislation, parliament, ministries, budgets, official appointments, regulation and the day-to-day running of the state. | — |
| ↳ `politics_elections` | Campaigns, candidates, polling, results, party organisation and coalition-building. | — |
| ↳ `politics_diplomacy` | Foreign relations, treaties, state visits, sanctions and international organisations. | — |
| ↳ `politics_protest` | Demonstrations, activism, civil dissent and political movements. | A strike over pay, which is labour_work. |
| **`crime_justice`** *(fallback — only if two below apply equally)* | Crime, policing and the legal system. | Legislation being debated, which is politics_government. |
| ↳ `crime` | Criminal acts, perpetrators, victims, police investigations, arrests and fraud reported as an offence. | — |
| ↳ `judiciary_courts` | Trials, verdicts, sentencing, judges, court rulings and the judiciary as an institution. | — |
| **`business_economy`** *(fallback — only if two below apply equally)* | Companies, markets and the economy. | A tech company's product launch, which is tech_consumer. |
| ↳ `business_companies` | Corporate results, mergers, executives, layoffs, strategy and the fortunes of individual firms. | — |
| ↳ `business_markets` | Stocks, currencies, commodities, bonds, investing and public offerings. | — |
| ↳ `business_macroeconomy` | GDP, inflation, employment figures, trade, taxation and central banks. | — |
| **`technology`** *(fallback — only if two below apply equally)* | Computing, the internet, devices and the technology industry. | Government regulation of tech, which is politics_government. Research findings, which is science_research. |
| ↳ `tech_ai` | Artificial intelligence, machine learning, models, chatbots and their applications. | — |
| ↳ `tech_security` | Cybersecurity, breaches, hacking, malware, privacy and surveillance. | An arrest for online fraud, which is crime. |
| ↳ `tech_consumer` | Devices, gadgets, apps, operating systems, product launches and reviews. | — |
| ↳ `tech_industry` | Technology companies as businesses, startups, funding, chips, platforms and infrastructure. | — |
| **`science_space`** *(fallback — only if two below apply equally)* | Scientific research and spaceflight. | Medical and public-health research, which is health. |
| ↳ `science_research` | Physics, biology, chemistry, archaeology, palaeontology and discovery. | — |
| ↳ `space` | Astronomy, space missions, satellites, rockets and spaceflight. | — |
| **`entertainment_arts`** *(fallback — only if two below apply equally)* | Entertainment, the arts and cultural life. | — |
| ↳ `entertainment_media` | Film, television, streaming, music, celebrity and the media industry. | — |
| ↳ `arts_culture` | Books, visual art, theatre, dance, design, heritage and museums. | — |
| **`society_lifestyle`** *(fallback — only if two below apply equally)* | Society, work and daily life. | — |
| ↳ `society_community` | Human interest, religion, festivals, migration, communities, charity and social issues. | — |
| ↳ `labour_work` | Unions, strikes over pay or conditions, wages, hiring, workplace rights and careers. | — |
| ↳ `lifestyle_living` | Travel, food, fashion, relationships, wellbeing, homes and hobbies. | — |
| **`health`** | Medicine, disease, public health, hospitals, mental health, nutrition and drugs. | Health insurance markets, which is business_economy. |
| **`education`** | Schools, universities, exams, admissions, curriculum, teachers and students. | — |
| **`environment_climate`** | Climate change, pollution, conservation, wildlife, the energy transition and natural resources. | A natural disaster as it happens, which is disaster_accident. |
| **`disaster_accident`** | Earthquakes, floods, storms, fires, industrial and transport accidents, and the emergency response to them. | The long-run climate context, which is environment_climate. |
| **`conflict_war`** | Armed conflict, military operations, terrorism, insurgency, peace talks and their humanitarian consequences. | Defence procurement debated in parliament, which is politics_government. |
| **`sport`** | Matches, tournaments, players, teams, transfers, doping and the bodies that govern sport. | — |
| **`unsorted`** | Anything else, or genuinely unclear. | — |

## Why some rows repeat across sheets

40 articles appear in every sheet on purpose. Comparing how differently two people labelled the same article is what tells us whether the classes are well defined. Do not coordinate on them.

## Returning the sheet

Keep the `article_id` column exactly as it is — it is how labels are matched back.
Do not add, remove or reorder rows. Save as CSV, keeping UTF-8 encoding.
