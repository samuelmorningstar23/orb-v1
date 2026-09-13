# Tyre model reference data: sources and verification

Procured 2026-09-13 (IST) for `proto/tyreformer/`. Every value was read from a page
fetched during this session. Nothing was filled from memory, and no Kaggle file or third-party CSV mirror was used.

## Files

| File | Rows | Contents |
|---|---|---|
| `pirelli_compounds.csv` | 82 (2023: 21, 2024: 24, 2025: 23, 2026: 14) | Dry compounds nominated as Hard, Medium and Soft per event. All 82 rows have `verified=true` and no blanks. |
| `circuits.csv` | 25 (the union of event keys) | Circuit name, official length, corner count and type. No blanks. The Pirelli severity-rating columns are omitted (see below). |

## pirelli_compounds.csv

### Primary source (the `source_url` column)

These are Pirelli's own compound-nomination press releases. They are listed on press.pirelli.com under the tags
"2023 Tyre Compound Choices" to "2026 Tyre Compound Choices"; the 2025 season-opener release is untagged. The text was
downloaded with curl and read directly: sentences mentioning C0 to C6 were extracted and transcribed by hand into the CSV.

One exception: the 2023 release for Bahrain, Saudi Arabia and Australia gives the compounds only as images. Those three
rows therefore cite formula1.com's article on the same announcement, which states them in text.

- 2023: Azerbaijan, Miami <https://press.pirelli.com/2023-tyre-compound-choices--azerbaijan-usa-and-italy/>
- 2023: Austria, Britain, Canada <https://press.pirelli.com/2023-tyre-compound-choices--canada-austria-and-great-britain/>
- 2023: Barcelona, Monaco <https://press.pirelli.com/2023-tyre-compound-choices--monaco-and-spain/>
- 2023: AbuDhabi <https://press.pirelli.com/a-soft-landing-for-the-2023-world-championship/>
- 2023: Monza, Zandvoort <https://press.pirelli.com/news-and-tyre-choices-for-zandvoort-and-monza/>
- 2023: Brazil, Mexico, USA <https://press.pirelli.com/two-confirmations-and-an-innovation-in-the-tyre-choices-for-the-american-continent/>
- 2023: Belgium, Hungary <https://press.pirelli.com/tyre-news-and-nominations-for-hungary-and-belgium/>
- 2023: Japan, Qatar, Singapore <https://press.pirelli.com/unchanged-nominations-for-singapore-japan-and-qatar--in-name-at-least/>
- 2023: Australia, Bahrain, SaudiArabia <https://www.formula1.com/en/latest/article.pirelli-confirm-tyre-choices-for-first-three-f1-races-of-2023-as-new.1xlpcTVaLqw0NeM3aYoyCt.html>
- 2024: Azerbaijan, Monza, Singapore <https://press.pirelli.com/a-soft-september-for-pirelli-in-f1-compounds-confirmed-for-monza-baku-and-singapore/>
- 2024: Belgium, Hungary, Zandvoort <https://press.pirelli.com/all-compounds-on-track-over-next-three-races/>
- 2024: AbuDhabi, LasVegas, Qatar <https://press.pirelli.com/all-compounds-on-track-to-end-the-season/>
- 2024: Austria, Barcelona, Britain <https://press.pirelli.com/no-surprises-for-the-compounds-for-spain-austria-and-great-britain/>
- 2024: Australia, Bahrain, SaudiArabia <https://press.pirelli.com/pirelli-nominates-the-compounds-for-the-start-of-2024/>
- 2024: Canada, Imola, Monaco <https://press.pirelli.com/same-soft-trio-for-imola-monaco-and-montreal/>
- 2024: China, Japan, Miami <https://press.pirelli.com/these-are-the-p-zero-compounds-for-suzuka-shanghai-and-miami/>
- 2024: Brazil, Mexico, USA <https://press.pirelli.com/these-are-the-tyres-for-the-americas/>
- 2025: Australia, Bahrain, China, Japan, SaudiArabia <https://press.pirelli.com/2025-compounds-something-new-for-jeddah/>
- 2025: Austria, Belgium, Britain, Hungary <https://press.pirelli.com/both-new-and-familiar-for-spielberg-to-budapest/>
- 2025: AbuDhabi, Azerbaijan, Brazil, Mexico, Monza, Qatar, Singapore, USA, Zandvoort <https://press.pirelli.com/changes-and-status-quo-when-it-comes-to-compound-choices-for-the-rest-of-the-season0/>
- 2025: Barcelona, Canada, Monaco <https://press.pirelli.com/from-monaco-to-montreal-all-the-compounds-in-play/>
- 2025: Imola, Miami <https://press.pirelli.com/pirelli-on-the-soft-side-for-miami-and-imola/>
- 2026: Australia, China, Japan <https://press.pirelli.com/complete-f1-tyre-range-for-the-first-three-grands-prix-of-2026/>
- 2026: Belgium, Hungary <https://press.pirelli.com/the-compounds-selected-for-belgium-and-hungary/>
- 2026: Austria, Britain <https://press.pirelli.com/the-full-pirelli-range-for-spielberg-and-silverstone/>
- 2026: Canada, Miami <https://press.pirelli.com/the-softest-trio-for-the-challenges-of-miami-and-montreal/>
- 2026: Barcelona, Monaco <https://press.pirelli.com/the-tyre-compound-selections-for-monte-carlo-and-barcelona/>
- 2026: Madrid, Monza, Zandvoort <https://press.pirelli.com/tyre-compounds-selected-for-zandvoort-monza-and-madrid/>

Hard, Medium and Soft map to the lowest, middle and highest C-number of the nominated trio. A few releases list only the
numbers ("C3, C4 and C5"). For every such row, at least one cross-check source below states the designation explicitly
("designated hard, medium, and soft, respectively").

### Cross-checks (the `note` column says which agreed: `xcheck WP+F1+PV agree`)

- **WP**, all 82 rows: each English Wikipedia race article's Background sentence ("Tyre supplier Pirelli brought the Cx,
  Cy and Cz tyre compounds ...") was pulled through the MediaWiki API and parsed automatically. The result was **82 of 82
  identical** to the primary values. For 2025 and 2026 these sentences cite Pirelli's race-week previews, so they reflect
  the final nominations, not only the advance announcement.
- **PV**, 36 rows (every 2025 and 2026 row): Pirelli's own race-week preview for the event, published days before the
  race, was fetched and read. **36 of 36 agree**, so no nomination was changed between announcement and race week.
- **F1**, 40 rows across all four seasons (2023: 10, 2024: 11, 2025: 9, 2026: 10): formula1.com's race-week article "What
  tyres will the teams and drivers have for the ... Grand Prix?" was fetched and read. **40 of 40 agree.** Three of those
  rows are the formula1.com-sourced 2023 opener rows; only 2023 Australia also has a race-week article.

**Conflicts: none.** No source disagreed with another on any of the 82 rows.

### Modelling caveats stated in the fetched sources

C-numbers are not the same rubber across seasons, so treat (season, C-number) as the identifier, not the C-number alone.

- **2023**: a six-compound range, C0 to C5. The 2022 C1 was renamed C0, and a new C1 was slotted between the old C1 and
  C2 (Pirelli 2023 opener release; formula1.com).
- **2024**: five compounds, C1 to C5. The C0 was dropped, and formula1.com reported the FIA as saying the compounds were
  otherwise the same as 2023.
- **2025**: six compounds, C1 to C6, with the C6 new. The C2 (especially) and the C3 were revised softer, the C4 and C5
  were modified against graining, and the C1 is closest to its 2024 version (Pirelli 2025 Australia, China and Japan
  previews).
- **2026**: new, smaller tyres (reduced contact patch and diameter, 18-inch rim) and **five compounds, C1 to C5. There is
  no C6 in 2026** (Pirelli 2026 Australia preview; Miami/Montreal release: "Last year, when the range extended up to
  C6"). Every 2026 value is therefore 1 to 5.
- Non-consecutive trios, all in 2025: Belgium C1/C3/C4, USA C1/C3/C4, Mexico C2/C4/C5. The C6 was used in 2025 at Imola
  (its debut), Monaco, Canada and Azerbaijan.
- Context for the 2026 keys: Pirelli's 2026 Miami preview mentions "the cancellation of the Bahrain and Saudi Arabian
  Grands Prix", and a later release lists a 2026 "Bahrain Grand Prix" hosted at Sepang. Neither is in the requested key
  list.

### Cross-check URLs

formula1.com race-week articles:
- 2024 LasVegas <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-las-vegas-grand-prix.ufsYJ5HkKWCc65K1yWydN>
- 2024 Canada <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-canadian-grand-prix.3xS2raatSWhmFr3YlQxBd3>
- 2024 Monza <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-italian-grand-prix.2oO1jaVl2vB25F16qcFMPH>
- 2024 Barcelona <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-spanish-grand-prix.7rLCqBvroeRw7HVW8GGChP>
- 2024 Brazil <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-sao-paulo-grand-prix.6vKgx4XLiN5It5wtiYXqsL>
- 2024 USA <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-united-states-grand.8QfDCtgqiePxAvvNol577>
- 2024 Austria <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-austrian-grand-prix.501nkNqLI40inoC4Tdf4w6>
- 2024 Bahrain <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-bahrain-grand-prix.6XY3WMWfBQV97jQz2NkVFw>
- 2024 Britain <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-british-grand-prix.3vzK0q1kbEOjzwGClOCXoF>
- 2024 Zandvoort <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-dutch-grand-prix.5p57LNOThFxzf35X7eMWQi>
- 2024 Miami <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2024-miami-grand-prix.3WEEez2FIT763XYXEBcc14>
- 2023 USA <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-united-states-grand.24UsOsaCszDcdoTFNZVcIl>
- 2023 Britain <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-british-grand-prix.I8A8IlnQDX1YauQHSgY5Q>
- 2023 Mexico <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-mexico-city-grand.MAS6QQvlCln4LZmnPQRr9>
- 2023 Monza <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-italian-grand-prix.6h2cQeDiNp8Wqs6lj4ArWJ>
- 2023 Austria <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-austrian-grand-prix.4uQiByAubQKgLekMk3g5Rz>
- 2023 AbuDhabi <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-abu-dhabi-grand-prix.64CNIc1wzgQmwUqJCWG1Q0>
- 2023 Miami <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-miami-grand-prix.2cyD0jxr7HUNNeLtlPyJGb>
- 2023 Japan <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-japanese-grand-prix.4AG2oXMnZ3lk57gxUrUKKD>
- 2023 Qatar <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-qatar-grand-prix.7lwS2mAXKyyh7Un1AV8RVp>
- 2023 Australia <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2023-australian-grand.qj6Jp6a0TEoHXtdSwRdie>
- 2026 Monaco <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-monaco-grand-prix.6RNlF5Skp9niWsEz6urQMr>
- 2025 Monza <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-italian-grand-prix.7fO9Z1g1aG6QUGhXzg8gLU>
- 2025 AbuDhabi <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-abu-dhabi-grand-prix.7dAs4svUzCpUlKIdh20q4Y>
- 2025 Qatar <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-qatar-grand-prix.5uM7XCc74nzDcQgtnJivy9>
- 2025 Australia <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-australian-grand.6BHZAGXShd5oMNiVGtcofW>
- 2025 Monaco <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-monaco-grand-prix.2vbcWNeFsxMEZMojG7UXFA>
- 2025 Barcelona <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-spanish-grand-prix.5R3UWCrzQEzL5nW91ulSlk>
- 2025 USA <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-united-states-grand.iA1RRCtPcRcMlIZqdQP3G>
- 2025 Miami <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-miami-grand-prix.1PVJRhU0GRuJZ7yvWOzq5V>
- 2025 Mexico <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2025-mexico-city-grand.321Njw4EBFbhCUVrZWOb6f>
- 2026 Britain <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-british-grand-prix.3qD9d5o8X4x3se0F7Zg5i1>
- 2026 Australia <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-australian-grand.4Uli9fb5X7hNAhkxzikv5B>
- 2026 Miami <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-miami-grand-prix.3IDiDRC753kNe02Qwia4V1>
- 2026 Canada <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-canadian-grand-prix.2Olo6kVcWh1n3FfU0OancF>
- 2026 Zandvoort <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-dutch-grand-prix.402ufleb78rXrqaispof9U>
- 2026 Monza <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-italian-grand-prix.7nOpWdCgvCBFDGlnODs0gk>
- 2026 Japan <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-japanese-grand-prix.4V0p1BrC3PbEiWNzsivaSr>
- 2026 Madrid <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-spanish-grand-prix.2vlcVOBnZUFRCooVcqWG7n>
- 2026 Austria <https://www.formula1.com/en/latest/article/what-tyres-will-the-teams-and-drivers-have-for-the-2026-austrian-grand-prix.2bhUStvp9xxGLpN2gvTeib>

Pirelli race-week previews:
- 2025 AbuDhabi <https://press.pirelli.com/in-abu-dhabi-for-a-first-step-towards-the-f1-of-the-future/>
- 2025 Australia <https://press.pirelli.com/under-starters-orders-in-melbourne-and-something-new-on-the-podium/>
- 2025 Austria <https://press.pirelli.com/a-hot-summer-of-formula-1-gets-underway-in-austria/>
- 2025 Azerbaijan <https://press.pirelli.com/the-c6-is-back-for-baku/>
- 2025 Bahrain <https://press.pirelli.com/in-bahrain-with-prior-knowledge/>
- 2025 Barcelona <https://press.pirelli.com/the-hardest-tyres-are-back-for-spain/>
- 2025 Belgium <https://press.pirelli.com/sprint-with-a-jump-in-compounds-in-the-ardennes/>
- 2025 Brazil <https://press.pirelli.com/harder-compounds-for-the-sao-paulo-sprint-weekend/>
- 2025 Britain <https://press.pirelli.com/formula-1-goes-back-to-the-cradle/>
- 2025 Canada <https://press.pirelli.com/formula-1-heads-for-montreal-with-its-overtaking-and-changeable-weather/>
- 2025 China <https://press.pirelli.com/a-chinese-weekend-that-presents-many-challenges-as-well-as-something-new/>
- 2025 Hungary <https://press.pirelli.com/hungary-hits-40-before-the-summer-break/>
- 2025 Imola <https://press.pirelli.com/the-c6-to-make-its-debut-in-imola/>
- 2025 Japan <https://press.pirelli.com/to-suzuka-for-something-new-and-something-old/>
- 2025 Mexico <https://press.pirelli.com/once-again-a-skip-in-compounds-for-the-mexico-city-weekend/>
- 2025 Miami <https://press.pirelli.com/a-sprint-n-soft-grand-prix-in-miami/>
- 2025 Monaco <https://press.pirelli.com/two-pit-stops-mandatory-in-monaco/>
- 2025 Monza <https://press.pirelli.com/art-history-and-speed-monza-gets-ever-more-special/>
- 2025 Qatar <https://press.pirelli.com/another-desert-this-time-in-doha/>
- 2025 SaudiArabia <https://press.pirelli.com/a-softer-approach-for-jeddah/>
- 2025 USA <https://press.pirelli.com/a-texas-rodeo-with-a-jump-in-compounds/>
- 2025 Zandvoort <https://press.pirelli.com/there-at-the-start-75-years-ago-pirelli-hits-the-500-grands-prix-mark/>
- 2026 Australia <https://press.pirelli.com/melbourne-writes-the-first-chapter-of-the-new-f1-season/>
- 2026 Austria <https://press.pirelli.com/red-bull-at-home-the-spielberg-weekend/>
- 2026 Barcelona <https://press.pirelli.com/six-months-on-formula-1-returns-to-barcelona/>
- 2026 Belgium <https://press.pirelli.com/formula-1-faces-its-spa-francorchamps-exam/>
- 2026 Britain <https://press.pirelli.com/the-challenges-of-silverstone-the-cradle-of-motorsport/>
- 2026 Canada <https://press.pirelli.com/the-first-sprint-in-montreal/>
- 2026 China <https://press.pirelli.com/the-first-sprint-of-the-season-in-shanghai/>
- 2026 Hungary <https://press.pirelli.com/the-heat-is-on-in-budapest/>
- 2026 Japan <https://press.pirelli.com/the-suzuka-challenge-with-the-hardest-trio-in-the-range/>
- 2026 Madrid <https://press.pirelli.com/the-madring-makes-its-world-championship-debut-with-the-challenge-of-the-monumental/>
- 2026 Miami <https://press.pirelli.com/formula-1-returns-to-the-track-in-miami/>
- 2026 Monaco <https://press.pirelli.com/the-jewel-of-formula-1-history-and-glamour-at-the-monaco-gp/>
- 2026 Monza <https://press.pirelli.com/pirelli-headlines-italian-grand-prix-weekend-at-monza/>
- 2026 Zandvoort <https://press.pirelli.com/in-the-netherlands-with-the-sprint-format/>

Wikipedia race articles use the title pattern "<season> <Grand Prix name>" (for example "2025 United States Grand Prix").
The 2026 Barcelona row uses "2026 Barcelona-Catalunya Grand Prix", and 2026 Madrid uses "2026 Spanish Grand Prix".

## circuits.csv

`source_url` holds several URLs separated by `|`: the formula1.com race page, the Wikipedia circuit article, the Wikipedia
"List of Formula One circuits", and, for `hybrid` rows, the Pirelli page that justifies that type.

- **length_km**: the "Circuit Length" field on formula1.com's race page (`/en/racing/<season>/<slug>`). It comes from
  the latest season in our data for that event (2026 where the event is in the 2026 keys, otherwise 2025, and 2024 for
  Las Vegas). All 25 values match the current Grand Prix layout in the Wikipedia circuit infobox. Lengths that changed
  inside 2023 to 2026, per formula1.com:
  - Austria was 4.318 km in 2023 and 2024, and 4.326 km in 2025 and 2026.
  - Singapore was 4.940 km in 2023 and 2024, and 4.927 km in 2025.
  - The CSV holds the latest value.
- **corners**: the `turns` value for the current Grand Prix layout (layout 1) in each Wikipedia circuit infobox. Pirelli
  or formula1.com text states the same count for 23 of the 25 circuits (Jeddah's 27 comes from formula1.com's race
  page). No text count was found for Belgium or Singapore.
- **circuit_type**: taken from the Type column of Wikipedia's list: Street circuit becomes `street`, Race circuit becomes
  `permanent`, and Road circuit becomes `hybrid`. There is one override to `hybrid`, used where Pirelli or formula1.com
  text explicitly calls a venue semi-permanent or part street and part permanent:
  - Albert Park: "semi-permanent street circuit" (Pirelli 2025 preview and formula1.com).
  - Circuit Gilles Villeneuve: "semi-permanent" (Pirelli 2025 and 2026 previews).
  - Madring: "combines a street section ... with a second, permanent section" (Pirelli), and "combine a street-circuit
    and permanent set-up feel" (formula1.com).
  - Miami and Jeddah stay `street`. For Miami, formula1.com says "a temporary circuit" and Pirelli says "a street
    circuit". For Jeddah, formula1.com says "a temporary street circuit (albeit adorned with some permanent sections)".
- **Conflicts found and how they were resolved:**
  - Albert Park turns: the Wikipedia list says 16 (the pre-2021 layout); the circuit infobox and formula1.com ("14-corner")
    say 14. Resolved to **14**.
  - Spa turns: the Wikipedia list says 20; the infobox for the 2007-present Grand Prix layout says 19. Resolved to **19**.
    No third source was found.
  - Madring length: the Wikipedia list says 5.474; the Pirelli preview says 5.416; formula1.com and the Wikipedia infobox
    say 5.414. Resolved to **5.414**.
  - Silverstone length: the Pirelli 2025 preview says 5.861 km; formula1.com (all seasons), the Wikipedia infobox and the
    Pirelli 2026 preview say 5.891. Resolved to **5.891**.
  - Red Bull Ring length: the Pirelli May 2025 release says 4.318; formula1.com 2025 and 2026, the Pirelli 2026 preview and
    the Wikipedia infobox say 4.326. Resolved to **4.326** (the current layout).
- **Pirelli 1-5 severity ratings** (traction, braking, lateral, tyre stress, asphalt grip, asphalt abrasion, track
  evolution, downforce) were **not added**:
  - On press.pirelli.com they appear only inside infographic images (`Visual-Preview-XX25-EN`, `Visual-Preview-XX26-EN`).
    A text search of all 36 fetched 2025 and 2026 previews found none of the ratings as text.
  - The only text versions found are partial third-party blog paraphrases for single 2026 races (e.g.
    coffeecornermotorsport.com for Madrid, blog.f1livepulse.com for Hungary), and they omit some axes.
  - That is not a full season as text, so the columns were skipped as instructed.
