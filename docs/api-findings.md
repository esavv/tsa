# TSA Security Wait Times – API Findings

## Summary

**JFK**, **LGA**, and **EWR** use the same backend API. You can get structured wait-time data with a simple HTTP GET and the right headers, no headless browser or OCR required for this path.

---

## API

| Item | Value |
|------|--------|
| **Base URL** | `https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/{AIRPORT}` |
| **Method** | GET |
| **Airport codes** | `LGA`, `JFK`, `EWR` |

### Headers (required)

The API returns **401 Unauthorized** without these. Use the matching airport origin:

- **LGA:**  
  `Referer: https://www.laguardiaairport.com/`  
  `Origin: https://www.laguardiaairport.com/`
- **JFK:**  
  `Referer: https://www.jfkairport.com/`  
  `Origin: https://www.jfkairport.com/`
- **EWR:**  
  `Referer: https://www.newarkairport.com/`  
  `Origin: https://www.newarkairport.com/`

### Example (curl)

```bash
# LGA
curl -sS -H "Referer: https://www.laguardiaairport.com/" -H "Origin: https://www.laguardiaairport.com/" \
  "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/LGA"

# JFK
curl -sS -H "Referer: https://www.jfkairport.com/" -H "Origin: https://www.jfkairport.com/" \
  "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/JFK"

# EWR
curl -sS -H "Referer: https://www.newarkairport.com/" -H "Origin: https://www.newarkairport.com/" \
  "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/EWR"
```

---

## Response shape

JSON **array** of objects. One object per terminal × queue type (General = `Reg`, TSA Pre✓ = `TSAPre`).

| Field | Type | Description |
|-------|------|-------------|
| `pointID` | int | Unique ID for this checkpoint/queue |
| `terminal` | string | e.g. `"A"`, `"1"`, `"4"` |
| `title` | string | e.g. `"Terminal A"`, `"Terminal 1"` |
| `gate` | string | e.g. `"All Gates"` |
| `queueType` | string | `"Reg"` (general) or `"TSAPre"` |
| `timeInMinutes` | int | Wait time in minutes |
| `timeInSeconds` | int | Wait time in seconds |
| `status` | string | e.g. `"Open"`, `"No Wait"` |
| `isWaitTimeAvailable` | bool | Whether a numeric wait is shown |
| `updateTime` | string | ISO 8601, e.g. `"2026-03-12T00:57:00"` |
| `updateTimeText` | string | e.g. `"12:57 AM"` |
| `updateDateTimeText` | string | e.g. `"03/12/2026 12:57 AM"` |
| `queueOpen` | bool | Whether the queue is open |
| `area` | string | `"TSA"` |
| `checkPoint` | string | e.g. `"Main ChekPoint"` (typo in API) |

### Normalization for storage

- **General line** → `queueType === "Reg"`
- **TSA Pre✓ line** → `queueType === "TSAPre"`
- "No Wait" → `timeInMinutes === 0` and often `isWaitTimeAvailable === false`
- Use `updateTime` (or your scrape timestamp) for “last updated” in your DB.

---

## Source

Discovered via Cursor browser MCP: opened [laguardiaairport.com](https://www.laguardiaairport.com/), reloaded, and called `browser_network_requests`. The XHR list included:

- `https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints/LGA`
- Same host also used for parking, walk times, taxi wait times, alerts, and datetime config (e.g. `/api/v1/parking/LGA`, `/api/v1/walkTimes/LGA`, `/api/v1/TaxiWaitTimePoints/LGA`, `/api/v1/alerts/LGA`, `/api/v1/DateTimeConfigSettings/LGA`).

JFK and EWR use the same path with their matching airport codes; no separate browser test is needed once headers are set to the corresponding airport origin.
