# Test Plan: T21 · Fault-scenario orchestrator — labelled windows as Grafana annotations

## Setup

- The scenarios read what the delivery's verification runs of `chaos/run.py` wrote to Grafana on this cluster: `t21-pelny` (S1–S7 with `--gap 1m`), `t21-s7` (S7 alone, `--gap 0s`), and `t21-ctrlc-s6` / `t21-ctrlc-s7` (S6 / S7 interrupted by SIGINT 40 s / 30 s after launch) (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239, 1318, 1330-1335). The harness cannot run the host CLI, so these runs must exist before `/qa:run` starts; no scenario recreates them.
- BE-04 and BE-06 also read Prometheus series from the windows of these runs. Prometheus keeps them on its volume for 3 days (deploy/observability/values/kube-prometheus-stack.yaml:22-31), so `/qa:run` must start within 3 days of the runs.
- Grafana keeps the annotations in its own database, and the `grafana` values configure no persistent storage for it (deploy/observability/values/kube-prometheus-stack.yaml:70-90), so a recreated Grafana pod has lost them. The Grafana pod in `monitoring` must not have been recreated since the verification runs; otherwise repeat the runs before `/qa:run`, after removing their `reports/runs/<run-id>/` directories, which the orchestrator refuses to reuse (chaos/run.py:473-474).

## Source
- Type: last 3 commits (`git diff HEAD~3...HEAD`; HEAD~3 is `3e09239`, "docs: add delivery plan t21-orkiestrator-scenariuszy")
- Base: main
- Date: 2026-11-24
- Branch: t21-orkiestrator-scenariuszy
- Head: 6622478ca6adcfee78e19adf376c13a7252a5eff

## Changes Summary

All three commits carry the trailer `Delivery-Plan: docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md` (issue #21). The path was accepted: repository-relative, no `..`, no symlink on the path, a regular file inside the repository. Its Context, tasks and Verification are the specification for this plan.

- `0710dd0`, Task 1 "S1 trwa 4 min: domyślny czas awarii cpu w orders": the default `seconds` of orders' `POST /faults/cpu` rises from 120 to 240 (services/orders/src/orders/faults.py:236, within `Seconds` 1–3600 at line 40); `services/orders/tests/test_faults.py` pins it.
- `7e235c8`, Task 2 "Orkiestrator chaos/run.py": a new host CLI runs S1–S7 through `kubectl exec` in `loadgen/fault-runner` and `intruder/intruder`, with a `--gap` sleep before every scenario and after the last (chaos/run.py:224-243). Each closed window becomes one line of `reports/runs/<run-id>/labels.jsonl` and, right after it, one organisation-wide Grafana region annotation: `POST /api/annotations` with `time`/`timeEnd` in ms, tags `scenario` and the scenario ID, and text `<ID> <nazwa> → <cel>, przebieg <run-id>` (chaos/run.py:319-358). Ctrl+C kills the S6/S7 in-pod process, sends `fault-runner stop` and closes the open window (chaos/run.py:290-300). Unit tests with fakes: `chaos/tests/test_run.py`.
- `6622478`, Task 3 "Dokumentacja kontraktu orkiestratora i S1 = 4 min": `docs/architektura.md` (S1 = 4 min, S7 on the orders pod IP, the orchestrator contract and the tag-based annotation query for T22; lines 342-381), `docs/detekcja.md` (gap semantics at line 13, S1/HighCPU timing at line 80) and `README.md` (usage; lines 117-127).

File classes: BE — `chaos/run.py` (its server-side effect is the annotation store of target `grafana`) and `services/orders/src/orders/faults.py` (served by orders, which BE-05 names as target `orders`; the config has no such target yet). Neither — `README.md`, `docs/architektura.md`, `docs/detekcja.md`, `chaos/tests/test_run.py`, `services/orders/tests/test_faults.py`. No FE or DESKTOP file changed; FE-01 still uses Grafana's UI, because acceptance criterion 2 is about the windows drawn on a dashboard by the annotation query documented in docs/architektura.md:368-377, which no committed dashboard carries until T22.

Through target `grafana` the plan reads the annotations of the verification runs (acceptance criterion 1 as one annotation per window, and criterion 2; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:12-14), their retrieval by tag and by time range, the signal each scenario's command left in Prometheus inside its window, that S1's 4-min window makes `HighCPU` fire, and the regions the documented query draws on a temporary dashboard. Through target `orders` it checks the new 240-s default of the cpu fault.

## Blockers / Findings

None found.

## Users
- grafana_admin: existing — Grafana administrator from Secret `monitoring/grafana-admin` (keys `admin-user`, `admin-password`), login `admin` with a random password (README.md:60; docs/architektura.md:316, 322); `chaos/run.py` posts the annotations with this same account (chaos/run.py:380-400, 476-480). No sign-up flow creates it, so it must be configured; its email field must hold the login `admin` (or the account's e-mail), which the BE scenarios use as the Basic auth user name and FE-01 types into the login form.

No owner/other-user pair applies: annotations without `dashboardUID` belong to the whole Grafana organisation (docs/architektura.md:368), and the change adds no per-user resource. One BE-01 edge case sends no credentials, to confirm the annotations are not public: the Grafana values configure no anonymous access (deploy/observability/values/kube-prometheus-stack.yaml:70-90). The orders fault routes take no user either: they check one shared `X-Fault-Token` value (services/orders/src/orders/faults.py:221-231), which BE-05 sends from a configured value.

## Detected Tools
- Playwright MCP: available (FE-01)
- HTTP client: curl (httpie unavailable); jq and perl JSON::PP available for response inspection
- Store clients: psql and sqlite3 available; mysql and redis-cli unavailable. No store is configured and no scenario needs a State Check.
- Desktop drivers: none

## FE Test Scenarios

**Window-closing states.** Two independent inputs decide how a window, and so its annotation, ends: how the scenario ends — a timer for S1–S5 or a blocking in-pod command for S6 and S7 (chaos/run.py:106-167, 249-253) — and what happens to the run while the window is open — it completes, Ctrl+C arrives, or a scenario command fails after all attempts (chaos/run.py:229-243). Full 2 × 3 product, for the FE and BE scenarios below:

| Row | Window ends by | Run while the window is open | Classification | Disposition |
|---|---|---|---|---|
| 1 | timer (S1–S5) | completes | real | FE-01, BE-01 (`t21-pelny` S1–S5), BE-03, BE-04, BE-06 (S2–S5) |
| 2 | blocking command (S6, S7) | completes | real | FE-01, BE-01 (`t21-pelny` S6, S7), BE-02 (`t21-pelny`, `t21-s7`), BE-06 (S6, S7) |
| 3 | timer (S1–S5) | Ctrl+C | real (chaos/run.py:234-237, 290-300) | out of harness scope — no verification run interrupted S1–S5, and the harness cannot run the CLI; chaos/tests/test_run.py:271 covers it with fakes |
| 4 | blocking command (S6, S7) | Ctrl+C | real (chaos/run.py:290-300) | BE-02 (`t21-ctrlc-s7`; `t21-ctrlc-s6` in its first edge case), BE-06 edge cases (the in-pod process ended with the window) |
| 5 | timer (S1–S5) | command fails after 5 attempts | real (chaos/run.py:238-241, 255-266) | out of harness scope — no verification run failed a scenario, and the harness cannot make `kubectl exec` fail; chaos/tests/test_run.py:256 covers it with fakes |
| 6 | blocking command (S6, S7) | command fails | real (chaos/run.py:238-241, 255-266) | out of harness scope — same reason as row 5 |

### FE-01: The documented tag query draws the seven `t21-pelny` windows on a dashboard
- **Area:** Grafana's dashboard UI with the annotation query documented for T22 (docs/architektura.md:368-377): the visual part of acceptance criterion 2, scenario windows visible as annotations on dashboards (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:12-14, 1313). State rows 1 and 2.
- **Target:** grafana
- **Writes:** yes
- **Preconditions:**
  1. Open `/login`, fill "Email or username" with `$QA_GRAFANA_ADMIN_EMAIL` and "Password" with `$QA_GRAFANA_ADMIN_PASSWORD`, and click "Log in".
  2. In the same tab open `/api/datasources` and retain PROM_UID = the `uid` of the first item whose `type` is `prometheus` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1272).
  3. Open `/api/annotations?tags=scenario&tags=S1&limit=1000` and retain FROM = `time` − 60000 of the item whose `text` is `S1 cpu → orders, przebieg t21-pelny`; open `/api/annotations?tags=scenario&tags=S7&limit=1000` and retain TO = `timeEnd` + 60000 of the item whose `text` is `S7 scan → orders, przebieg t21-pelny` (epoch ms). If either item is missing, report `NEED_INFO kind=fixture` for the run `t21-pelny` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239).
- **Steps:**
  1. Open `/dashboard/import`.
  2. Paste this dashboard (D1), with PROM_UID replaced, into "Import via dashboard JSON model", click "Load", then "Import". Its `annotations.list` entry is the documented one verbatim (docs/architektura.md:371-377):
     ```json
     {
       "uid": "qa-t21-scenariusze",
       "title": "QA T21 scenariusze",
       "schemaVersion": 39,
       "annotations": {"list": [{
         "name": "Scenariusze",
         "datasource": {"type": "grafana", "uid": "-- Grafana --"},
         "enable": true,
         "iconColor": "red",
         "target": {"type": "tags", "tags": ["scenario"], "matchAny": false, "limit": 100}
       }]},
       "panels": [{
         "id": 1, "type": "timeseries", "title": "CPU / limit",
         "gridPos": {"x": 0, "y": 0, "w": 24, "h": 10},
         "datasource": {"type": "prometheus", "uid": "PROM_UID"},
         "targets": [{"refId": "A", "expr": "service:cpu_usage_ratio_of_limit"}]
       }]
     }
     ```
  3. Open `/d/qa-t21-scenariusze?from=FROM&to=TO`.
  4. Hover each annotation marker along the bottom of the "CPU / limit" panel, note its tooltip, and take a screenshot of the panel.
- **Expected:** The panel draws its CPU series and exactly 7 red annotation regions, one per `t21-pelny` window, S1 to S7 from left to right. Each tooltip shows the window's text and its two tags, e.g. `S1 cpu → orders, przebieg t21-pelny` with the tags `scenario` and `S1`; the 7 texts are the ones BE-01 lists (chaos/run.py:338-346; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1313) (unverified — confirm at run time)
- **Edge cases:**
  - Import D1 again with `uid` `qa-t21-s7`, `title` `QA T21 S7` and the entry's `tags` set to `["scenario", "S7"]`, then open `/d/qa-t21-s7?from=FROM&to=TO`: exactly one region, whose tooltip shows `S7 scan → orders, przebieg t21-pelny`, because with `matchAny: false` an annotation must carry every listed tag (chaos/run.py:341; docs/architektura.md:376) (unverified — confirm at run time)
  - Import D1 again with `uid` `qa-t21-bez-zapytania`, `title` `QA T21 bez zapytania` and no `annotations` key, then open `/d/qa-t21-bez-zapytania?from=FROM&to=TO`: the panel draws its CPU series but no annotation region, because the orchestrator's annotations carry no `dashboardUID` and Grafana's built-in "Annotations & Alerts" query shows only the dashboard's own (chaos/run.py:338-346; docs/architektura.md:368; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:54) (unverified — confirm at run time)
- **Cleanup:** After the edge cases, open `/dashboards`, search `QA T21`, select the three imported dashboards, click "Delete" and confirm.

## BE Test Scenarios

BE-01 to BE-04 and BE-06 use target `grafana` and send only GET requests; BE-05 uses target `orders`. Sort annotations by `time` before checking their order. A duration is `(timeEnd − time) / 1000` in seconds.

### BE-01: The full run `t21-pelny` left one annotation per window, S1–S7 in order
- **Area:** Grafana's annotation API, where `chaos/run.py` posts one region annotation per closed window (chaos/run.py:319-358): acceptance criterion 1 (a full S1–S7 run gives 7 windows) and the API side of criterion 2 (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:12-14). State rows 1 and 2.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** The `t21-pelny` run from Setup. If no item of the response has a `text` ending in `, przebieg t21-pelny`, report `NEED_INFO kind=fixture` for "annotations of verification run t21-pelny (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239)".
- **Method:** GET /api/annotations?tags=scenario&limit=1000
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none
- **Expected:** 200 with a JSON array of annotation objects carrying `time`, `timeEnd`, `tags` and `text` (unverified — confirm at run time). Exactly 7 items have a `text` ending in `, przebieg t21-pelny`, because each closed window's label line is followed by exactly one annotation (chaos/run.py:332-335). Sorted by `time`, their `text` values are exactly `S1 cpu → orders, przebieg t21-pelny`, `S2 memory → orders, przebieg t21-pelny`, `S3 errors → orders, przebieg t21-pelny`, `S4 latency → orders, przebieg t21-pelny`, `S5 crash → orders, przebieg t21-pelny`, `S6 spike → frontend, przebieg t21-pelny` and `S7 scan → orders, przebieg t21-pelny`: the text rule, the scenario table and the default S1–S7 order (chaos/run.py:342-345, 106-165, 440). Each has exactly the two tags `scenario` and its own ID (chaos/run.py:341). Every `time` and `timeEnd` is a whole second in ms, divisible by 1000 (chaos/run.py:339-340, 373-374). Durations: exactly 240 for S1 and exactly 180 for each of S2–S5, the table time each window waits out (chaos/run.py:109-136, 252); 180–185 for S6 and 120–125 for S7, whose windows close only when the blocking in-pod command returns (chaos/run.py:55, 59-67, 144-146, 156-162, 249-253; docs/architektura.md:360). Between consecutive windows, the next `time` minus the previous `timeEnd` is 60000–62000 ms, the `--gap 1m` sleep before every scenario (chaos/run.py:230-232; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239). None of the 7 is bound to a dashboard: `dashboardUID` is empty, null or absent and `panelId` is 0 or absent, because the request body carries no dashboard field (chaos/run.py:338-346; docs/architektura.md:368) (unverified — confirm at run time)
- **Edge cases:**
  - The same request without the Authorization header: 401 and no annotation array, because the Grafana values configure no anonymous access (deploy/observability/values/kube-prometheus-stack.yaml:70-90) (unverified — confirm at run time)
  - Every item of the main response, whatever its run id, has exactly the tags `scenario` and one ID from S1–S7, and a `text` of the form `<ID> <name> → <target>, przebieg <run-id>` with the name and target listed above for that ID and a run id matching `[A-Za-z0-9][A-Za-z0-9._-]*` (chaos/run.py:106-165, 341-345, 516-521)

### BE-02: Per-scenario tags return the completed and the Ctrl+C-cut windows of S7 and S6
- **Area:** The per-scenario tag that dashboards (T22) and detection evaluation (T30) filter on (chaos/run.py:341; docs/architektura.md:368), and the Ctrl+C contract: an interrupted run closes and annotates its open window (chaos/run.py:234-237, 290-300; docs/architektura.md:381; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1339). State rows 2 and 4.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** The `t21-pelny`, `t21-s7`, `t21-ctrlc-s6` and `t21-ctrlc-s7` runs from Setup. If a response below lacks the item of one of these run ids, report `NEED_INFO kind=fixture` naming that run (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239, 1318, 1330-1335).
- **Method:** GET /api/annotations?tags=S7&limit=1000
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none
- **Expected:** 200 with a JSON array (unverified — confirm at run time). Every item has exactly the tags `scenario` and `S7` and a `text` of the form `S7 scan → orders, przebieg <run-id>` (chaos/run.py:151-154, 341-345). The items include exactly one each for the run ids `t21-pelny`, `t21-s7` and `t21-ctrlc-s7`; other run ids may also appear. The `t21-pelny` and `t21-s7` windows ran the 120-s scan to its end, so each lasts 120–125 s (chaos/run.py:59-67, 156-162, 249-253; docs/architektura.md:360). The `t21-ctrlc-s7` window was cut by SIGINT: the orchestrator kills the in-pod scan, sends `fault-runner stop`, then closes and annotates the open window (chaos/run.py:290-300, 319-335). The verification sent SIGINT 30 s after launch, so this window lasts 27–33 s (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1334-1335)
- **Edge cases:**
  - GET /api/annotations?tags=S6&limit=1000: 200; every item has exactly the tags `scenario` and `S6` and a `text` of the form `S6 spike → frontend, przebieg <run-id>` (chaos/run.py:139-142, 341-345). The `t21-pelny` item lasts 180–185 s, because the window closes when the 180-s spike returns (chaos/run.py:55, 144-146, 249-253). Exactly one `t21-ctrlc-s6` item lasts 37–43 s: SIGINT came 40 s after launch, and the window closed after the PID-file kill and `fault-runner stop` (chaos/run.py:294-297; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1330-1331)
  - GET /api/annotations?tags=scenario&tags=S1&limit=1000, where both tags must match, as in the documented dashboard query with `matchAny: false`: 200; every item has exactly the tags `scenario` and `S1` and a `text` of the form `S1 cpu → orders, przebieg <run-id>`, and the `t21-pelny` item lasts exactly 240 s (chaos/run.py:109, 252, 341-345; docs/architektura.md:376) (unverified — confirm at run time)
  - GET /api/annotations?tags=S8&limit=1000: 200 with an empty array, because the orchestrator defines only S1–S7 and rejects any other ID before touching the cluster (chaos/run.py:106-167, 494-503) (unverified — confirm at run time)

### BE-03: A time-range query returns exactly the windows that overlap it
- **Area:** Retrieval of windows by time range, which a dashboard's time picker applies to the tag query (docs/architektura.md:368-377; README.md:127). State row 1.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** GET /api/annotations?tags=scenario&limit=1000 with the headers below. From the 7 items whose `text` ends in `, przebieg t21-pelny`, retain in epoch ms: FROM = `time` of S1, TO = `timeEnd` of S7, S2_END = `timeEnd` of S2, S3_START = `time` of S3 and S3_END = `timeEnd` of S3. If these items are missing, report `NEED_INFO kind=fixture` for the run `t21-pelny` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239).
- **Method:** GET /api/annotations?tags=scenario&from=FROM&to=TO&limit=1000
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none; FROM and TO from the precondition
- **Expected:** 200 with exactly the 7 `t21-pelny` items of the precondition, S1–S7, and no item of another run: a run writes windows only between its own start and end (chaos/run.py:224-243), and the verification ran its orchestrator runs one at a time (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1230, 1239, 1318, 1330-1335) (unverified — confirm at run time)
- **Edge cases:**
  - The main request with from = S3_START and to = S3_END: 200 with exactly one item, `S3 errors → orders, przebieg t21-pelny`, because S2 ends and S4 starts at least 60 s away, across the `--gap 1m` sleeps (chaos/run.py:230-232; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239) (unverified — confirm at run time)
  - The main request with from = S2_END + 10000 and to = S3_START − 10000, a range inside the gap before S3: 200 with an empty array, because no window is open while the orchestrator sleeps between scenarios (chaos/run.py:230-232, 245-253) (unverified — confirm at run time)

### BE-04: S1's 4-minute window makes HighCPU fire for orders
- **Area:** The reason S1 now lasts 4 min: `HighCPU` (`service:cpu_usage_ratio_of_limit > 0.8` for 2 min, evaluated every 30 s) must fire during S1 (deploy/observability/alert-rules.yaml:15-22; docs/architektura.md:347, 355; docs/detekcja.md:80; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1263), read through Grafana's Prometheus data source proxy. State row 1.
- **Target:** grafana
- **Writes:** no
- **Preconditions:**
  1. GET /api/annotations?tags=scenario&tags=S1&limit=1000 with the headers below. From the item whose `text` is `S1 cpu → orders, przebieg t21-pelny`, retain S1_START = `time` / 1000 and S1_END = `timeEnd` / 1000 (Unix seconds). If it is missing, report `NEED_INFO kind=fixture` for the run `t21-pelny` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239).
  2. GET /api/datasources with the same headers: 200; retain PROM_UID = the `uid` of the first item whose `type` is `prometheus` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1272).
- **Method:** GET /api/datasources/proxy/uid/PROM_UID/api/v1/query_range
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none; URL-encoded query parameters `query` = `ALERTS{alertname="HighCPU", alertstate="firing", service="orders"}`, `start` = S1_START, `end` = S1_END + 120 and `step` = `15`
- **Expected:** 200 with `status` `success` and `data.resultType` `matrix` (unverified — confirm at run time). `data.result` holds at least one series whose `metric` has `alertname` `HighCPU`, `alertstate` `firing`, `service` `orders`, `namespace` `shop`, `detector` `rules` and `severity` `warning`, with at least one value `"1"` (deploy/observability/alert-rules.yaml:17-22; deploy/observability/recording-rules.yaml:21-23; docs/architektura.md:303). Its first timestamp is at least S1_START + 120, because the condition must hold for 2 min after the fault starts (deploy/observability/alert-rules.yaml:19; docs/detekcja.md:80) (unverified — confirm at run time)
- **Edge cases:**
  - The same query with `start` = S1_START − 55 and `end` = S1_START − 5, inside the `--gap 1m` before S1: 200 with an empty `data.result`, so HighCPU was not already firing for orders and the firing above comes from S1 (chaos/run.py:230-232; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239) (unverified — confirm at run time)
  - The same request with `query` = `service:cpu_usage_ratio_of_limit{service="orders"}`, `start` = S1_START, `end` = S1_END + 120 and `step` = `30`: 200 with one series labelled `namespace` `shop` and `service` `orders` (deploy/observability/recording-rules.yaml:19-23). Its values are above 0.8 at every point from S1_START + 120 to S1_END − 30 and below 0.8 at every point from S1_END + 90 on: the 1-min rate stays above 0.8 from about 48 s after the fault starts until about 12 s after it ends, and the fault lasts the window's 240 s (docs/detekcja.md:80; chaos/run.py:109) (unverified — confirm at run time)

### BE-05: Orders' cpu fault lasts 240 s when `seconds` is omitted
- **Area:** Orders' `POST /faults/cpu`, whose default `seconds` rose from 120 to 240 so that S1's 4 min holds for any client of the fault API (services/orders/src/orders/faults.py:235-237; docs/architektura.md:338, 347). The route is active in the `local` overlay (deploy/overlays/local/kustomization.yaml:49-63) and served in the cluster by Service `orders` on port 8080 (deploy/base/orders/service.yaml:8-13), which no configured target reaches yet.
- **Target:** orders
- **Writes:** yes
- **Preconditions:** `$QA_FAULT_SECRET` holds key `token` of Secret `fault-token` in namespace `shop`, which orders reads as `FAULT_TOKEN` (docs/architektura.md:321; deploy/base/orders/deployment.yaml:45-51). No fault needs to be stopped first: a new fault replaces the current one (services/orders/src/orders/faults.py:144-149).
- **Method:** POST /faults/cpu
- **Headers:** X-Fault-Token: `$QA_FAULT_SECRET`
- **Payload:** none, and no query string
- **Expected:** 202 with a JSON object whose `fault` is `cpu` and whose `ends_at` is a UTC ISO 8601 time 235–240 s after the response arrived by the tester's clock: `ends_at` is the start time plus `seconds`, which defaults to 240 (services/orders/src/orders/faults.py:155, 235-237). Right after it, POST /faults/stop with the same header: 200 with `stopped` equal to `cpu`, so the fault does not burn CPU for the full 4 min (services/orders/src/orders/faults.py:99-109, 281-283)
- **Edge cases:**
  - POST /faults/cpu without the `X-Fault-Token` header, and again with `X-Fault-Token: nope`: 403 each, with a `detail` string `invalid or missing fault token` from the router's dependency, before the route runs (services/orders/src/orders/faults.py:221-231) (exact text — brittle)
  - With the header, POST /faults/cpu?seconds=0 and POST /faults/cpu?seconds=3601: 422 each, with `detail[0].loc` equal to `["query", "seconds"]`, because `seconds` must lie in 1–3600 (services/orders/src/orders/faults.py:40, 236; .venv/lib/python3.13/site-packages/fastapi/exception_handlers.py:23-26). After the main flow and both edge cases, POST /faults/stop with the header: 200 with `stopped` null, since no rejected request started a fault (services/orders/src/orders/faults.py:99-104, 281-283)

### BE-06: Each scenario's command left its signal inside its own `t21-pelny` window
- **Area:** What the in-pod commands of S2–S7 did (chaos/run.py:110-165), seen through the `service:*` recording rules that alerts and detection read (deploy/observability/recording-rules.yaml:1-9) via Grafana's Prometheus data source proxy, and that Ctrl+C ends the S6 and S7 in-pod process (chaos/run.py:294-297). The delivery expects each window's region to lie over its scenario's rise (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1313). S1 is BE-04. State rows 1, 2 and 4.
- **Target:** grafana
- **Writes:** no
- **Preconditions:**
  1. GET /api/annotations?tags=scenario&limit=1000 with the headers below. Sort the 7 items whose `text` ends in `, przebieg t21-pelny` by `time`. For each of S2–S7 retain, in Unix seconds, its window W = [`time` / 1000, `timeEnd` / 1000] and the gap before it G = [`timeEnd` / 1000 of the previous item, `time` / 1000 of this item]. If these items are missing, report `NEED_INFO kind=fixture` for the run `t21-pelny` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1239).
  2. GET /api/datasources with the same headers: 200; retain PROM_UID = the `uid` of the first item whose `type` is `prometheus` (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1272).
- **Method:** GET /api/datasources/proxy/uid/PROM_UID/api/v1/query_range, once for each scenario below
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none; URL-encoded query parameters `query` = the scenario's expression below, `start` = the start of its G, `end` = the end of its W and `step` = `15`
- **Expected:** Each request: 200 with `status` `success` and one series labelled `namespace` `shop` and the expression's `service` (deploy/observability/recording-rules.yaml:2) (unverified — confirm at run time). The gap level is the series' maximum over G and the window peak its maximum over W; for every scenario the window peak is above the gap level:
  - S2, `service:memory_working_set_ratio_of_limit{service="orders"}`: the rise is the whole assertion. The memory fault sizes its allocation from `memory.current` (services/orders/src/orders/faults.py:81-91), while the rule divides the container's working set (deploy/observability/recording-rules.yaml:37-53), so the peak need not reach HighMemory's 0.85 (deploy/observability/alert-rules.yaml:29); that level belongs to the memory fault, not to the orchestrator, which sends S2 as the table defines it (chaos/run.py:115; docs/architektura.md:348) (unverified — confirm at run time)
  - S3, `service:http_errors_ratio:rate1m{service="orders"}`: window peak above 0.05, HighErrorRate's threshold, since every second `/orders` response is a 500 during the fault (chaos/run.py:122; services/orders/src/orders/faults.py:164-171; deploy/observability/alert-rules.yaml:40; docs/architektura.md:340)
  - S4, `service:http_latency_p95_seconds:1m{service="orders"}`: window peak above 0.3, HighLatency's threshold, since each `/orders` request waits 500 ms during the fault (chaos/run.py:129; services/orders/src/orders/faults.py:96-97, 116-117; deploy/observability/alert-rules.yaml:51)
  - S5, `service:restarts:increase5m{service="orders"}`: window peak above 0, because each crash ends the orders process with exit code 1 and the container restarts (chaos/run.py:136; services/orders/src/orders/faults.py:211-213, 271-279; deploy/observability/recording-rules.yaml:106-113)
  - S6, `service:http_requests:rate1m{service="frontend"}`: the rise is the whole assertion, because no rule has a threshold for a traffic spike; the 50 spike users add tens of requests per second to Locust's 1–9 (chaos/run.py:55; docs/architektura.md:329, 332, 352)
  - S7, `service:policy_drops:rate1m{service="orders"}`: 0 at every point of G and window peak above 0, because the rule yields 0 without drops and the scan's probes to the orders pod are dropped as `POLICY_DENIED` (chaos/run.py:59-67; deploy/observability/recording-rules.yaml:114-137; docs/architektura.md:353, 355)
- **Edge cases:**
  - Ctrl+C in S6 ended the spike: GET /api/annotations?tags=S6&limit=1000 and retain W = [`time` / 1000, `timeEnd` / 1000] of the item whose `text` ends in `, przebieg t21-ctrlc-s6`. Then the main request with `query` = `service:http_requests:rate1m{service="frontend"}`, `start` = W start − 120 and `end` = W end + 150: 200; with BEFORE = the maximum over [W start − 120, W start] and PEAK = the maximum over [W start, W end + 30], PEAK is above BEFORE and every point from W end + 105 to W end + 135 is below (BEFORE + PEAK) / 2. The PID-file kill before the window closes ends the spike (chaos/run.py:54-55, 294-297); an unkilled spike would run 180 s from its start, about 140 s past this 40-s window (chaos/run.py:55; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1330-1331) (unverified — confirm at run time)
  - Ctrl+C in S7 ended the scan: GET /api/annotations?tags=S7&limit=1000 and retain W of the item whose `text` ends in `, przebieg t21-ctrlc-s7`. Then the main request with `query` = `service:policy_drops:rate1m{service="orders"}`, `start` = W start and `end` = W end + 150: 200; some point from W start to W end + 30 is above 0, and every point from W end + 105 to W end + 135 is 0. The kill ends the scan loop as the window closes (chaos/run.py:59-67, 294-297); an unkilled scan would probe for 120 s from its start, about 90 s past this 30-s window, so its drops would still fall in the rule's 1-min rate at those points (chaos/run.py:60; deploy/observability/recording-rules.yaml:122; docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1334-1335) (unverified — confirm at run time)

## Out of harness scope
- `reports/runs/<run-id>/labels.jsonl` and `run.json`: 7 lines for a full run, key order `scenario`, `name`, `target`, `start`, `end`, UTC ISO 8601 times, `commit`, and `end` null while running — host files that no configured target serves.
- The CLI surface: validation of `--scenarios`, `--gap` and `--run-id`, refusal of an existing run directory, exit codes 0, 1, 2 and 130, the stdout `run`/`start`/`end` lines, the stderr `interrupted` and `warning:` messages, and the stop before any scenario when the Secret read, `GET /api/org` or the commit lookup fails — the harness cannot run a host CLI.
- The in-pod commands themselves: the `kubectl exec` argv of each scenario, the up to 5 attempts 2 s apart, the S5 crashes at 0, 60 and 120 s, and on Ctrl+C the PID-file `kill` and `fault-runner stop` commands — `kubectl exec` traffic and pod processes are visible through no HTTP target, and the `service:*` rules BE-06 reads show only their aggregate effect.
- S7's per-port verdicts: probes to ports 8080, 22, 80, 443, 5432 and 6379 of the orders pod IP, each dropped as `POLICY_DENIED` — per-port flow verdicts come only from `hubble observe` through Hubble Relay (docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md:1316-1321), which no configured target exposes, and the rule BE-06 reads sums drops over ports (deploy/observability/recording-rules.yaml:117-137).
- Windows cut by Ctrl+C during S1–S5 or ended by a failing scenario command (state rows 3, 5 and 6), and Ctrl+C during a gap, which writes no window (chaos/run.py:321-322) — no verification run produced them, and the harness cannot run the CLI to make one.
