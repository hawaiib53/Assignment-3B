# Discord AQI Alert Bot

Checks the [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api)
forecast for a given ZIP code and posts an alert to a Discord webhook
whenever the forecasted US AQI is above 50 — so you know when it's a good
time to get some fresh air.

Alerts are rate-limited to at most one per hour (configurable), even if
the script runs more often.

## How it works

1. Resolves the configured ZIP code to latitude/longitude via the free
   [Zippopotam.us](https://www.zippopotam.us/) geocoding API.
2. Fetches the hourly `us_aqi` forecast from Open-Meteo for that
   location.
3. Reads the AQI value for the current forecast hour.
4. If it's above the threshold (default 50) and no alert was sent within
   the last hour (default), posts an embed to the configured Discord
   webhook titled **"AQI Index over 50"** in red (`#FF0000`), including
   the specific AQI value.

Nothing is hardcoded — the webhook URL, ZIP code, threshold, and rate
limit are all read from environment variables.

## Setup

1. Create a Discord webhook: Server Settings → Integrations →
   Webhooks → New Webhook, then copy the webhook URL.
2. Copy `.env.example` to `.env` and fill in `DISCORD_WEBHOOK_URL`
   (and adjust `ZIP_CODE` or other values if desired).
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Run it:

   ```bash
   set -a && source .env && set +a
   python aqi_alert_bot.py
   ```

## Configuration (environment variables)

| Variable                      | Required | Default               | Description                                      |
|--------------------------------|----------|-----------------------|---------------------------------------------------|
| `DISCORD_WEBHOOK_URL`           | Yes      | —                     | Discord webhook to post alerts to                  |
| `ZIP_CODE`                      | No       | `54017`               | ZIP code to check the AQI forecast for             |
| `COUNTRY_CODE`                  | No       | `us`                  | Country code for the ZIP lookup                   |
| `AQI_THRESHOLD`                 | No       | `50`                  | Alert when forecasted AQI exceeds this value       |
| `MIN_ALERT_INTERVAL_SECONDS`    | No       | `3600`                | Minimum time between Discord alerts                |
| `STATE_FILE`                    | No       | `state/last_alert.json` | Where the last-alert timestamp is persisted      |

## Running on a schedule

### Cron (self-hosted)

Run every 10-15 minutes; the script's own rate limit ensures Discord
only receives at most one alert per hour:

```cron
*/15 * * * * cd /path/to/repo && set -a && source .env && set +a && python3 aqi_alert_bot.py >> aqi_alert.log 2>&1
```

### GitHub Actions

A workflow is included at `.github/workflows/aqi-alert.yml` that runs
every 15 minutes. To use it:

1. Add a repository secret named `DISCORD_WEBHOOK_URL` with your webhook
   URL (Settings → Secrets and variables → Actions → New repository
   secret).
2. Optionally add a repository variable `ZIP_CODE` to override the
   default.
3. The workflow caches `state/last_alert.json` between runs so the
   one-per-hour rate limit is enforced even though each run is a fresh
   container.

## Notes on the Discord message format

Discord doesn't support arbitrary font colors in normal message text.
This bot gets as close as Discord allows:

- The embed's accent color (the vertical bar) is set to `#FF0000`.
- The message content wraps "AQI Index over 50" in an ANSI code block
  using Discord's supported red foreground color, which renders as red
  text on desktop/web clients.
- The embed body includes the specific AQI value, ZIP code, and forecast
  hour.
