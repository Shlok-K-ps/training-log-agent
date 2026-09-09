# Calendar, location, sleep and daily-plan integration

Repository: <https://github.com/Shlok-K-ps/training-log-agent>

## Product behaviour

The athlete connects Google Calendar from a short-lived link sent only to their
WhatsApp number. The application reads selected calendar event times and usable
locations for the requested day, fetches travel durations to and from the saved
gym, and runs a deterministic candidate-slot search.

The planner rejects overlaps and any slot that cannot fit:

1. travel from the preceding event or saved default place;
2. the configured pre-training buffer;
3. the full session duration;
4. the configured post-training buffer;
5. travel to the following event; and
6. the bedtime protection boundary.

Candidates are ranked by sleep recovery, commute cost and closeness to the
athlete's preferred training window. Same-day readiness can reduce or suppress
the load through the existing readiness engine. It can never increase the base
prescription. Severe recovery and open injury flags remain hard stops.

If sleep triggers a nap, options after the nap plus a 60-minute buffer rank above
earlier options. A completed nap requires another explicit readiness report; the
original night's sleep is retained. Confirming an updated option moves the
app-owned workout event rather than creating a duplicate.

The first-ranked training time is also passed into the existing food-access and
approved-supplement planner. Meal and supplement timing therefore moves with the
workout, while food choices remain limited to recorded access and exclusions.
Meals and approved supplements are shifted outside busy calendar windows;
bedtime supplements use the athlete's configured bedtime rather than a global
clock time.

## Human approval boundary

Planning is read-only. Every option has a short code. Only a WhatsApp message of
the form `confirm CODE` creates or updates an event, and it does so on a separate
`Power Coach` calendar created by the app. Meetings are never changed.

## Privacy boundary

- No continuous or background GPS tracking.
- Home, office and gym are athlete-supplied saved places.
- Calendar titles, descriptions, attendees and meeting content are neither
  requested in API fields nor persisted nor sent to the language model.
- Events without a usable location receive a configurable privacy/travel buffer;
  the application does not guess where the athlete is.
- OAuth tokens and saved places are encrypted with Fernet before SQLite storage.
- `disconnect calendar` deletes tokens; `forget my locations` deletes saved places.
- OAuth state is HMAC-signed, bound to the WhatsApp athlete identity and expires
  after 15 minutes.

Google recommends the narrowest OAuth scopes. This implementation uses
`calendar.events.readonly`, `calendar.calendarlist.readonly`, and
`calendar.app.created`, avoiding full-calendar write access. Public deployment
may require Google sensitive-scope verification:

- <https://developers.google.com/workspace/calendar/api/auth>
- <https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification>

Travel time comes from the Routes API rather than straight-line distance:

- <https://developers.google.com/maps/documentation/routes/compute_routes>

## Deployment

Create a Google Cloud OAuth web client and enable Google Calendar API and Routes
API. Configure the callback exactly as:

`https://YOUR_HOST/integrations/google/calendar/callback`

Set the five calendar variables documented in `.env.example`. For a public
launch, use separate Google Cloud projects for testing and production, publish
the `/`, `/privacy`, and `/terms` pages on a verified domain, restrict the Maps
key, and complete any OAuth verification Google requires.

WhatsApp setup sequence:

1. `connect my calendar`
2. follow the private link and grant access;
3. `my gym is ADDRESS` or `my gym is place_id:GOOGLE_PLACE_ID`
4. optionally save home and office and say which is the default location;
5. configure timezone, bedtime, training window, duration and travel mode;
6. `schedule my squat today`;
7. `confirm ABC123`.
