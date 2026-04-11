# Airport expansion research

Last updated: 2026-04-11

## Goal

Figure out which major U.S. airports appear to publish official security wait times, how those wait times are delivered, and what the least-annoying scrape approach would be for each one.

## TL;DR

Best next airports to add:

1. **LAX**: easiest, raw HTML table on official page
2. **MIA**: direct JSON API exposed by official site JS
3. **SEA**: direct JSON API exposed by official site JS
4. **DCA**: direct JSON endpoint behind official homepage widget
5. **DFW**: official live data exists, but scrape path needs more reverse engineering or a browser render

Lower-confidence / probably not worth doing yet:

- **ATL**: official page exists, but blocked behind bot protection in this environment
- **IAD**: same MWAA pattern as DCA, but current JSON looked placeholder / not production-usable
- **SFO**: official security info page found, but only checkpoint hours / advisory language, not live numeric waits
- **ORD**: official site found, but no live wait feed confirmed
- **BOS**: no usable live wait feed confirmed
- **DEN**: Cloudflare blocked inspection
- **FLL**: official security page linked, but page was unavailable from this environment

## Existing baseline

### JFK / LGA / EWR

These appear to share the same airport-authority/Azure-backed API family already used by the app.

Known working examples:

- `https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/JFK`
- `https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/LGA`
- `https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/EWR`

Notes:

- EWR worked when called with Newark `Referer` / `Origin` headers.
- This is the cleanest source family we have so far.

## Airport survey

| Airport | Official source found? | What we found | Delivery mechanism | Recommended approach | Confidence |
| --- | --- | --- | --- | --- | --- |
| LAX | Yes | `https://www.flylax.com/wait-times` shows terminal/lane/minutes table plus last-updated timestamp in raw HTML | Server-rendered HTML table | Plain requests + HTML parsing | High |
| MIA | Yes | Official page loads wait-times app bundle and points at `waittime.api.aero` | Vendor JSON API behind JS app | Call API directly with headers from official JS | High |
| SEA | Yes | Official page JS calls `/api/cwt/wait-times` and renders checkpoint list | First-party JSON endpoint | Call JSON directly | High |
| DCA | Yes | Homepage widget loads `/security-wait-times` and renders checkpoint table | First-party JSON endpoint | Call JSON directly | High |
| IAD | Partial | Same `/security-wait-times` endpoint exists, but response looked placeholder | First-party JSON endpoint, possibly incomplete | Manual validation before using | Medium |
| DFW | Yes | Official security page shows live checkpoint map/waits in rendered page | Client-rendered Next.js app | Headless browser first, reverse-engineer API later | Medium |
| ATL | Partial | Official `https://www.atl.com/times/` page exists, but inspection hit bot challenge | Unknown behind bot protection | Manual browser validation / stealth browser | Medium-low |
| SFO | Partial | Official security page lists checkpoint hours and mentions normal lines, but no live numeric waits found | Static content / advisory | Treat as no live source for now | Medium |
| ORD | Partial | Official O'Hare site/security widget found, but no live wait feed confirmed | Mostly static widget/content | Treat as no live source for now | Medium |
| BOS | Unclear | Official security info page exists, but usable live wait data not confirmed | Static or protected content | Manual validation needed | Low |
| DEN | Unclear | Official site blocked by Cloudflare in this environment | Unknown | Manual browser validation needed | Low |
| FLL | Unclear | Official security page linked from homepage, but page returned 503/unavailable here | Unknown | Manual validation needed | Low |

## Details by airport

### LAX

Official page:

- `https://www.flylax.com/wait-times`

What we verified:

- The page contains a normal HTML table with rows like terminal, lane type, and wait minutes.
- The page also includes a visible `Data Last Updated` timestamp in raw HTML.
- No browser automation is required for a first pass.

Practical scraper approach:

- Fetch page HTML
- Parse table rows
- Normalize terminal + lane names
- Parse `Data Last Updated`

Why this is good:

- Very low complexity
- Probably the fastest high-confidence expansion target after the NYC airports

### MIA

Official pages:

- `https://www.miami-airport.com/tsa-waittimes.asp`
- homepage widget on `https://www.miami-airport.com/`

What we verified:

- Official page loads JS from `/js/wait-times/...`
- The compiled JS hardcodes:
  - endpoint: `https://waittime.api.aero/waittime/v2/current/MIA`
  - header: `x-apikey: 5d0cacea6e41416fdcde0c5c5a19d867`
- Direct request with that header returned JSON successfully.

Example response fields:

- `queueName`
- `projectedMinWaitMinutes`
- `projectedMaxWaitMinutes`
- `status`
- `time`

Practical scraper approach:

- Skip browser rendering
- Call `waittime.api.aero` directly with the API key exposed by official site JS
- Transform queue names like `2 General`, `2 Priority`, `2 TSA-Pre`

Risks:

- Vendor-controlled API
- Key/header behavior could change
- May require separate per-airport discovery for other airports using the same vendor

### SEA

Official page:

- `https://www.portseattle.org/page/live-estimated-checkpoint-wait-times`

What we verified:

- Raw HTML loads custom Drupal JS:
  - `/modules/custom/pos_cwt_widget/js/pos_cwt.js`
- That JS calls:
  - `GET /api/cwt/wait-times`
- Direct JSON call worked.

Example response fields:

- `CheckpointID`
- `Name`
- `WaitTimeMinutes`
- `IsOpen`
- `Options`
- `IsDataAvailable`
- `LastUpdated`

The site JS converts values roughly like this:

- `< 5 min`
- `N min`
- `N - N+5 min`
- `N+ min`
- `Closed`

Practical scraper approach:

- Call `https://www.portseattle.org/api/cwt/wait-times`
- Reuse their formatting logic or store raw minutes/status and format in our app

Why this is good:

- Clean direct JSON
- No browser required
- Strong candidate for early rollout

### DCA

Official site:

- `https://www.flyreagan.com/`

What we verified:

- Homepage includes a `Security Checkpoint Wait Times` block
- Raw HTML contains a template placeholder and JS-rendering hooks
- Site JS calls:
  - `GET /security-wait-times`
- Direct JSON call worked.

Example response shape:

- `response.res.A.location`
- `response.res.A.waittime`
- `response.res.A.pre`
- `response.res.A.url`
- `response.header.*`

Observed output included values like:

- `Opens 4am`
- `< 5 mins`

Practical scraper approach:

- Call `https://www.flyreagan.com/security-wait-times`
- Parse per-checkpoint general + precheck values

Why this is good:

- Direct JSON
- No browser required
- Nice extension beyond the NYC/NJ cluster

### IAD

Official site:

- `https://www.flydulles.com/`

What we verified:

- `https://www.flydulles.com/security-wait-times` exists
- But current response looked like placeholder data:
  - one checkpoint only
  - `Terminal 1( )`
  - `Opens 4am`

Practical take:

- Same family as DCA/MWAA
- But not ready to trust without manual validation in a normal browser

Recommendation:

- Keep on research backlog, do not ship yet

### DFW

Official page:

- `https://www.dfwairport.com/security/`

What we verified:

- Official page explicitly says live wait times are shown on the map
- Page is a Next.js app with `__NEXT_DATA__`
- Browser-rendered DOM showed live checkpoint state and wait-time buckets
- JS bundle clearly models fields like:
  - `waitMinutes`
  - `waitTimePredictions`
  - `lastUpdatedTimeStamp`
  - `poiId`

Practical scraper approach:

Short term:

- Use headless browser render and scrape final DOM

Better later:

- Reverse-engineer the underlying API/XHR used by the Next app and switch to direct JSON

Why this is medium difficulty:

- Official data definitely exists
- But the clean API endpoint was not isolated yet

### ATL

Official page:

- `https://www.atl.com/times/`

What we verified:

- Official page exists
- Our environment hit bot protection / challenge pages when trying to inspect it
- Search snippets suggested the page really does publish live checkpoint times

Practical scraper approach:

- Needs manual browser validation first
- Could require a real browser session, stronger anti-bot handling, or endpoint discovery from devtools

Recommendation:

- Keep as a worthwhile target, but not the first one to build blindly

### SFO

Official page:

- `https://www.flysfo.com/passengers/flight-info/check-in-security`

What we verified:

- Official page lists checkpoint hours and screening options
- We found advisory language like `TSA Lines - Normal Wait Times`
- We did **not** confirm a public numeric live wait feed

Practical take:

- Good security-info page
- Not a confirmed live wait-time source

Recommendation:

- Treat as unsupported for now unless another official SFO page/API is found

### ORD

Official site:

- O'Hare official site / security widget assets under `flychicago.com`

What we verified:

- Security widget JS was found
- It appeared to handle simple day/night content behavior, not live wait JSON
- No usable official live wait feed was confirmed

Recommendation:

- Treat as unsupported for now

### BOS

Official page:

- `https://www.massport.com/logan-airport/at-the-airport/security-information`

What we verified:

- Official security info page exists
- Inspection was complicated by bot protection / Incapsula
- We did not confirm a usable live wait feed

Recommendation:

- Manual validation needed before doing engineering work

### DEN

Official site:

- `https://www.flydenver.com/`

What we verified:

- Cloudflare challenge blocked inspection in this environment
- No source confirmed yet

Recommendation:

- Manual browser validation needed

### FLL

Official site:

- Homepage links to security page under `fll.net`

What we verified:

- Security page path exists in site navigation
- Direct page fetches returned service unavailable from this environment
- No usable wait-time source confirmed yet

Recommendation:

- Manual browser validation needed

## Source families

This is the main architectural takeaway: this should not be modeled as one global scraper. It should be modeled as a small set of source-family adapters.

Suggested families:

1. **NYC Azure family**
   - JFK / LGA / EWR
   - Existing implementation pattern

2. **Raw HTML table family**
   - LAX
   - Straight HTML parsing

3. **Vendor JSON family**
   - MIA
   - Direct API call with headers discovered from official JS

4. **First-party JSON endpoint family**
   - SEA (`/api/cwt/wait-times`)
   - DCA (`/security-wait-times`)
   - Possibly IAD later if validated

5. **Browser-rendered app family**
   - DFW
   - likely ATL
   - Reverse-engineer later, headless fallback initially

6. **No confirmed live data**
   - SFO, ORD, BOS for now

## Recommended rollout order

### Tier 1: build now

- **LAX**
- **MIA**
- **SEA**
- **DCA**

Reason:

- High confidence
- Official sources verified
- Clean scrape paths
- Good geographic expansion quickly

### Tier 2: build after one more round of endpoint work

- **DFW**

Reason:

- Official live data definitely exists
- Just not fully isolated to a clean endpoint yet

### Tier 3: research backlog

- **ATL**
- **IAD**
- **DEN**
- **FLL**
- **BOS**

Reason:

- More anti-bot friction or incomplete validation

### Tier 4: probably not worth building until new evidence appears

- **SFO**
- **ORD**

Reason:

- We found security info, but not confirmed live numeric wait feeds

## Product / engineering recommendation

If we want this to scale, add an airport-source registry instead of growing one-off conditionals.

Something like:

- airport code
- source family
- source URL(s)
- request headers
- parse function
- lane normalization map
- confidence / last-verified timestamp

That lets us support a mixed fleet of:

- direct APIs
- HTML tables
- JSON widgets
- browser-rendered pages

without turning the scraper into spaghetti.

## Suggested immediate next build step

Implement the four easiest airports first:

- `LAX`
- `MIA`
- `SEA`
- `DCA`

That gets us:

- west coast
- southeast / Florida
- DC
- multiple new source families

and gives us a clean abstraction test before we touch harder cases like DFW or ATL.
