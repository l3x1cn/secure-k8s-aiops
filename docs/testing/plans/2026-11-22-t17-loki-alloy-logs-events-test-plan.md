# Test Plan: T17 logs and events (Loki, Grafana Alloy and the Grafana Loki data source)

## Source
- Type: last 5 commits (`git diff HEAD~5...HEAD`)
- Base: main
- Date: 2026-11-22
- Branch: t17-logi-zdarzenia
- Head: 8e08107768f88a2883a912cdd2474dc676835f0d

## Changes Summary

Four of the five commits name `docs/plans/2026-11-21-t17-logi-zdarzenia.md` in their own `Delivery-Plan:` trailer. The path was accepted: it is repository-relative, has no `..` segment and no symlinked component (`docs` and `docs/plans` are directories, the file is a regular file), and it resolves to a regular file inside the repository root. No trailer was rejected. The fifth commit, `a64af1df` "docs: add delivery plan t17-logi-zdarzenia", adds that plan and carries no trailer. The delivered files follow the plan's Tasks 1-4. docs/architektura.md:206 also says that Loki adds the stream label `service_name` itself, a sentence the plan's Task 4 text does not contain.

- `a104faf1` "feat(observability): Loki w make observability i źródło Loki w Grafanie (T17)", Delivery-Task-Title "Loki w make observability i źródło Loki w Grafanie", maps to plan Task 1:
  - `platform/versions.env:15-19`: Loki chart 21.2.3 (Loki 3.7.10) with its manifest digest.
  - `Makefile:18, 109, 120-123`: `make observability` installs release `loki` in `monitoring` as `<chart>@<digest>` with `--version`, after kube-prometheus-stack.
  - `deploy/observability/values/loki.yaml` (new): Monolithic (SingleBinary) mode with one replica (lines 6, 35-37), filesystem storage on a 5 Gi PVC (lines 13-14, 39-40), 72 h retention through the compactor (lines 25-30), `auth_enabled: false` (line 10); gateway, memcached caches, canary, helm test, rules sidecar and usage reporting off (lines 31-33, 56-76). Clients use the service `loki.monitoring.svc:3100` (lines 3-5).
  - `deploy/observability/values/kube-prometheus-stack.yaml:78-84`: Grafana data source `Loki`, type `loki`, uid `loki`, access `proxy`, URL host `loki.monitoring.svc`, port 3100.
- `3c0b61e9` "feat(observability): Grafana Alloy zbiera logi podów i zdarzenia Kubernetes do Lokiego (T17)", Delivery-Task-Title "Grafana Alloy: logi podów i zdarzenia Kubernetes", maps to plan Task 2:
  - `platform/versions.env:20-22`: Alloy chart 1.16.0 (Alloy v1.22.0) with its digest.
  - `Makefile:19, 110-111, 124-127`: release `alloy` is installed last.
  - `deploy/observability/values/alloy.yaml` (new): log files under `/var/log/pods` of pods in shop, loadgen, aiops and intruder on the instance's own node (lines 19-68); CRI parsing, the JSON field `level` promoted to a stream label and `filename` dropped (lines 70-89); Kubernetes events from the same namespaces as JSON lines with clustering, sent straight to Loki (lines 91-101); push to Loki's `/loki/api/v1/push` (lines 103-107); no PodLogs CRD, no usage reporting, UID 473 with GID 0, read-only root filesystem, no capabilities, `/tmp` on an emptyDir (lines 10-11, 108-145); a namespaced Role on pods and events instead of the chart's ClusterRole (lines 147-154).
- `cf11fc47` "test(observability): logi ERROR, zdarzenie BackOff i źródło Loki w Grafanie; uprawnienia konta Alloy (T17)", Delivery-Task-Title "Testy logów, zdarzeń, źródła Loki i uprawnień konta Alloy", maps to plan Task 3: `tests/observability/test_logs.py` (new: the Loki source and its health in Grafana, ERROR logs after `fault errors`, a `BackOff` event after two `fault crash`) and 12 `sa:monitoring/alloy` rows in `tests/security/test_rbac.py:63-66, 105-115`.
- `8e081077` "docs: Loki i Alloy (T17) w README, architekturze i modelu zagrożeń", Delivery-Task-Title "Dokumentacja", maps to plan Task 4: `README.md:41, 54, 78, 128-133`, `docs/architektura.md:13-14, 24, 93, 204-211` plus the repository-structure rows, and `docs/bezpieczenstwo.md:88, 111-112`.

The existing tests reach Loki through the Kubernetes API server proxy and start faults with `kubectl exec` (tests/observability/test_logs.py:27, 30, 56-81). No existing test reads Loki through Grafana's data source, or checks that `filename` is dropped, that only the four namespaces are collected, or that non-JSON lines carry no `level`.

Classification:
- FE and BE: `deploy/observability/values/kube-prometheus-stack.yaml` adds the data source that Grafana's HTTP API serves and its UI lists on target `grafana` (Makefile:165; docs/architektura.md:129). `deploy/observability/values/loki.yaml` and `deploy/observability/values/alloy.yaml` define the log store and the collector whose content Grafana serves through that data source: its proxy API, and Explore, the documented way to browse the logs (README.md:130). Covered by FE-01, FE-02 and BE-01 to BE-06.
- Neither: `Makefile` and `platform/versions.env` (install tooling and pins), `tests/observability/test_logs.py` and `tests/security/test_rbac.py` (test code), `README.md`, `docs/architektura.md`, `docs/bezpieczenstwo.md` and the delivery plan (documentation). Their verifiable effects are listed under Out of harness scope.

Intended contract, from the delivery plan's Context, Tasks 1-4 and Verification:
- Success paths:
  - Grafana has data source `Loki` with uid `loki`, and its health check returns `"status": "OK"` (docs/plans/2026-11-21-t17-logi-zdarzenia.md:11, 182-192, 215; tests/observability/test_logs.py:175-180).
  - Log streams carry `namespace`, `pod`, `container`, `stream` and `level`, and not `filename`; `namespace` values come only from aiops, intruder, loadgen and shop; `level` values include `INFO` (docs/plans/2026-11-21-t17-logi-zdarzenia.md:434-436). A line that is not JSON has no `level` (docs/architektura.md:206). Because `level` is a stream label, `| json` names the parsed field `level_extracted` and `level="ERROR"` matches the label (docs/plans/2026-11-21-t17-logi-zdarzenia.md:56).
  - Acceptance criterion 1: after `fault-runner fault errors`, `{namespace="shop", container="orders"} | json | level="ERROR"` returns orders entries, among them a 500 on route `/orders`, and the selector with `level="ERROR"` also returns entries without `| json` (docs/plans/2026-11-21-t17-logi-zdarzenia.md:6, 450; tests/observability/test_logs.py:183-200).
  - Acceptance criterion 2: `{job="loki.source.kubernetes_events"}` holds events, for example a `BackOff` Warning for a `Pod` after the second `fault-runner fault crash` within 10 min. Event lines are JSON with `name`, `kind`, `reason`, `type`, `count` and `msg` (docs/plans/2026-11-21-t17-logi-zdarzenia.md:7, 23, 25; docs/architektura.md:207; tests/observability/test_logs.py:203-222).
  - Each event reaches Loki once, and both Alloy pods form one cluster (docs/plans/2026-11-21-t17-logi-zdarzenia.md:815-826). Alloy runs hardened, with a Role limited to pods and events (docs/plans/2026-11-21-t17-logi-zdarzenia.md:57, 429-433; tests/security/test_rbac.py:105-115). Loki runs as one pod with the rendered objects and configuration of Task 1 (docs/plans/2026-11-21-t17-logi-zdarzenia.md:211-215). A repeated `make up` changes nothing in monitoring, and a fresh `make up` passes the test suites (docs/plans/2026-11-21-t17-logi-zdarzenia.md:827-847).
- Declared error paths: none returns an HTTP status. The delivery contingencies are CLI stop conditions: a digest mismatch in `helm upgrade`, a different rendered object list, `loki-0` not Ready, `permission denied` or `forbidden` in Alloy's log, an Alloy syntax error, no Loki source in Grafana, no `BackOff` within 120 s, one cluster peer or duplicate entries, a busy host port (docs/plans/2026-11-21-t17-logi-zdarzenia.md:866-876). The Alloy account's denials (secrets in shop and cluster-wide, configmaps in shop, pods in kube-system) are `kubectl auth can-i` answers (tests/security/test_rbac.py:112-115). Inside the harness the only error paths are Grafana's own: 401 without valid credentials and 404 for an unknown data source. This change does not alter them, and the values configure no anonymous access (deploy/observability/values/kube-prometheus-stack.yaml:70-90). The edge cases use them with the unverified tag.
- Inside the harness: target `grafana` (HTTP API, the Loki data source proxy, UI) and target `frontend` (anonymous requests whose request-log lines the scenarios then find in Loki). Target `mailpit` is not needed.
- Coverage limit: both acceptance criteria need a fault started with `kubectl exec` into `loadgen/fault-runner`, so neither runs as specified here. BE-03, BE-04 and FE-02 run the criterion's query shape (a selector on `namespace` and `container`, `| json`, a `level` filter) over entries the tester creates through the frontend, which logs a 4xx response as `WARNING` and a 2xx as `INFO` (docs/architektura.md:186). BE-06 reads the events the cluster recorded in the last 72 h; the harness cannot create one.

Evidence sources:
- Charts in the Helm cache are outside this working tree, so they are context, not `(path:line)` citations; read a member with `tar -xzOf <archive> <member>`:
  - kube-prometheus-stack 92.17.1, `~/.cache/helm/content/0b/0b5cdaf8dfd4dbfb8b857a025aead52fbd9b17d6fc95822f91792603ca30be9c.chart`, the digest in platform/versions.env:14. Its Grafana subchart is Grafana 13.3.0 (member `kube-prometheus-stack/charts/grafana/Chart.yaml`). The data source ConfigMap lists Prometheus, then Alertmanager, then every `additionalDataSources` entry (member `kube-prometheus-stack/templates/grafana/configmaps-datasources.yaml`, lines 29-39, 79-92 and 94-96). Prometheus, uid `prometheus`, is the default (member `kube-prometheus-stack/values.yaml`, lines 1606-1610), and Alertmanager has uid `alertmanager` (lines 1654-1656). The subchart's `grafana.ini` enables no anonymous access (member `kube-prometheus-stack/charts/grafana/values.yaml`, lines 1032-1049).
  - Loki chart 21.2.3, `~/.cache/helm/content/bd/bd02e2e55cdc0f0ac0cfbb2e01a01b7eba5316787a8ec38a35f315bbd405eed6.chart`: `appVersion: 3.7.10` (member `loki/Chart.yaml`) and image `docker.io/grafana/loki` without a tag override (member `loki/values.yaml`, lines 254-261).
  - Alloy chart 1.16.0, `~/.cache/helm/content/b5/b55a879497d59b66b65c9147d1e4fe3d25f93e18aff046bdf014fbcf8871ea87.chart`: `appVersion: v1.22.0` (member `alloy/Chart.yaml`).
- The code of Grafana 13.3.0, Loki 3.7.10, Alloy v1.22.0 and Locust 2.47.0 is not on disk. Their API responses, UI names and log formats carry the unverified tag.
- The frontend's 404 for an unknown path comes from Starlette 1.9.0 and FastAPI 0.162.5 installed in `.venv`, the versions that `uv.lock` pins for the images (services/frontend/Dockerfile:14-25).

## Blockers / Findings

### BLK-01: Loki accepts pushes and queries without authentication (`auth_enabled: false`, gateway off); an accepted, documented risk, not a contract defect — `(deploy/observability/values/loki.yaml:9-10)`
- **Impact on testing:** None on any scenario result. The delivery plan requires this setting (docs/plans/2026-11-21-t17-logi-zdarzenia.md:55). The chart's gateway, which can put basic authentication in front of Loki (Loki chart 21.2.3 member `loki/values.yaml`, lines 1534-1536, outside this working tree), is disabled (deploy/observability/values/loki.yaml:56-58), and docs/bezpieczenstwo.md:111 accepts the exposure as residual risk R1 until the `cloud` overlay (T29). Every scenario reaches Loki only through Grafana's credential-protected data source proxy, and those requests need no tenant header because of this setting. The exposure itself, any pod in the cluster reading or pushing entries at `loki.monitoring.svc:3100`, needs an in-cluster client and is listed under Out of harness scope.
- **Remediation (human Setup prerequisite):** None before this run.
- **Blocks:** none; no scenario is blocked by BLK-01.

## Users
- grafana_admin: existing — Grafana administrator created from Secret `monitoring/grafana-admin`, login `admin` with a random password that `make grafana-password` prints (scripts/secrets.sh:58-66; Makefile:172-175; README.md:59). No sign-up flow creates it, so it must be configured; its email field must hold the login `admin` (or the account's e-mail), which the scenarios use in Grafana's login form and as the Basic auth user name.

Requests to target `frontend` are anonymous, because the shop API has no login (services/frontend/src/frontend/app.py:94-126). No owner/other-user pair applies: Grafana data sources and Loki streams are shared by the whole Grafana organisation and cluster, and this change adds no per-user resource.

## Detected Tools
- Playwright MCP: available (OMP built-in browser)
- HTTP client: curl (httpie unavailable); jq and perl JSON::PP available for response inspection
- Store clients: psql and sqlite3 available; mysql and redis-cli unavailable. No store is configured and no scenario needs a State Check.
- Desktop drivers: none

## FE Test Scenarios

State combinations: whether a container's log line reaches Loki, and with which labels, depends on two independent inputs of the pod-log pipeline: whether the pod's namespace is one of shop, loadgen, aiops and intruder (deploy/observability/values/alloy.yaml:22-24), and whether the line is JSON with a `level` field (deploy/observability/values/alloy.yaml:76-83). The full 2 × 2 product is below and applies to FE-02, BE-03, BE-04 and BE-05. No invariant rules a row out, so every row is treated as real: shop runs JSON-logging services (services/frontend/src/frontend/__main__.py:9), loadgen runs Locust with its own text log (docs/architektura.md:263), and monitoring runs Grafana, Loki and Alloy itself, with Alloy's pods on the same worker nodes it reads (docs/plans/2026-11-21-t17-logi-zdarzenia.md:431).

| # | Namespace in Alloy's scope | JSON line with `level` | Classification | Outcome | Disposition |
|---|---|---|---|---|---|
| 1 | yes | yes | real | stored with `namespace`, `pod`, `container`, `stream` and `level`; no `filename` | FE-02, BE-03 (frontend `WARNING`), BE-04 (orders `INFO`), BE-05 (label names and `level` values) |
| 2 | yes | no | real | stored with `namespace`, `pod`, `container` and `stream`; no `level` | BE-05 edge case (Locust's lines in loadgen) |
| 3 | no | yes | real | not stored | BE-05 edge cases (namespace values; `{namespace=~"monitoring\|kube-system"}` is empty) and the FE-02 edge case on `{namespace="monitoring"}` |
| 4 | no | no | real | not stored | the same scenarios as row 3: discovery drops the pod before any line is parsed (deploy/observability/values/alloy.yaml:19-31), so the line format cannot change the outcome |

### FE-01: Grafana lists the provisioned Loki data source and its Test succeeds
- **Area:** Grafana 13.3.0 UI: Connections → Data sources and the Loki data source settings page. The source comes from `grafana.additionalDataSources` (deploy/observability/values/kube-prometheus-stack.yaml:78-84). Grafana's UI names are not on disk, so the UI expectations carry the unverified tag.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** None; the data source is provisioned at install, and logging in creates no data.
- **Steps:**
  1. Open `/login` in the browser.
  2. Fill "Email or username" with `$QA_GRAFANA_ADMIN_EMAIL` and "Password" with `$QA_GRAFANA_ADMIN_PASSWORD`, then click "Log in".
  3. Open `/connections/datasources`.
  4. Click the data source named `Loki`.
  5. On its settings page, click "Test" at the bottom.
- **Expected:** The data source list shows `Alertmanager`, `Loki` and `Prometheus`, with `Prometheus` marked as the default, so the added Loki source did not replace the chart's sources (deploy/observability/values/kube-prometheus-stack.yaml:78-84) (unverified — confirm at run time). The `Loki` settings page shows a connection URL with scheme `http`, host `loki.monitoring.svc` and port `3100`, and a notice that the source was provisioned by configuration and cannot be changed in the UI (deploy/observability/values/kube-prometheus-stack.yaml:80-84) (unverified — confirm at run time). After "Test", a success alert appears, for example `Data source successfully connected.` (unverified — confirm at run time) (exact text — brittle)
- **Edge cases:**
  - While still logged in, open `/api/datasources/proxy/uid/loki/config`, Loki's `/config` endpoint behind the data source's proxy: the page shows Loki's running configuration as YAML text with `auth_enabled: false`, `replication_factor: 1` under `common`, `object_store: filesystem` in the `schema_config` entry, a `retention_period` of 72 h (printed as `3d` or `72h`) under `limits_config` and `retention_enabled: true` under `compactor` (deploy/observability/values/loki.yaml:10, 12, 19, 27, 29) (unverified — confirm at run time)
  - Open `/logout`, then open `/connections/datasources/edit/loki`: Grafana redirects to `/login` and shows no data source settings, because the values configure no anonymous access (deploy/observability/values/kube-prometheus-stack.yaml:70-90) (unverified — confirm at run time)
  - On `/login`, fill "Email or username" with `$QA_GRAFANA_ADMIN_EMAIL` and "Password" with `nope`, then click "Log in" once: the browser stays on `/login` with an error alert such as `Invalid username or password`. Do not repeat the attempt, so the account is not locked by Grafana's failed-login protection (unverified — confirm at run time) (exact text — brittle)

### FE-02: Explore shows the tester's frontend request-log line from Loki
- **Area:** Grafana Explore with the `Loki` data source (README.md:130), showing a line that Alloy collected from the frontend container (deploy/observability/values/alloy.yaml:19-89). State row 1; the edge cases cover rows 3-4.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** In the browser, open `http://localhost:8080/qa-$QA_TAG-explore` (target `frontend`). The frontend has no such route (services/frontend/src/frontend/app.py:94-102), so the page shows the JSON body `{"detail":"Not Found"}` (.venv/lib/python3.13/site-packages/starlette/routing.py:633-634; .venv/lib/python3.13/site-packages/fastapi/exception_handlers.py:15-17), and the frontend's request-log middleware writes one JSON line to stdout with `level` `WARNING`, `route` `unmatched`, `status` 404 and `msg` `GET ` plus the request path (libs/observability/src/observability/__init__.py:53-66, 73, 103-130). Then log in to Grafana as in FE-01 steps 1-2, with `$QA_GRAFANA_ADMIN_EMAIL` and `$QA_GRAFANA_ADMIN_PASSWORD`.
- **Steps:**
  1. Open `/explore`.
  2. In the data source picker at the top, choose `Loki`.
  3. Switch the query editor from "Builder" to "Code".
  4. Replace the editor content with `{namespace="shop", container="frontend"} |= "qa-$QA_TAG-explore" | json | level="WARNING"`.
  5. Click "Run query". If no log line is listed, run it again every 10 s for up to 120 s (tests/observability/test_logs.py:37).
  6. Click the listed line to open its details.
- **Expected:** The logs view lists at least one line: the precondition's JSON line, containing `"level": "WARNING"`, `"service": "frontend"`, `"route": "unmatched"`, `"status": 404` and `GET /qa-` (libs/observability/src/observability/__init__.py:53-66, 112-130). Its details list `namespace` `shop`, `container` `frontend`, a `pod` whose name starts with `frontend-`, `level` `WARNING` and `stream` `stdout`, and no `filename` (deploy/observability/values/alloy.yaml:36-49, 73-88; deploy/base/frontend/deployment.yaml:4, 30) (unverified — confirm at run time)
- **Edge cases:**
  - Replace the query with `{namespace="shop", container="frontend", level="ERROR"} |= "qa-$QA_TAG-explore"` and run it: no log line is listed, because the 404 was logged at `WARNING` and the `level` label copies that field (libs/observability/src/observability/__init__.py:112-118; deploy/observability/values/alloy.yaml:76-83) (unverified — confirm at run time)
  - Replace the query with `{namespace="monitoring"}`, choose the time range "Last 24 hours" and run it: no log line is listed, although Grafana, Loki and Alloy run in monitoring, because Alloy discovers pods only in shop, loadgen, aiops and intruder (deploy/observability/values/alloy.yaml:22-24) (unverified — confirm at run time)

## BE Test Scenarios

### BE-01: Grafana serves the provisioned Loki data source
- **Area:** Grafana data source API. The `Loki` entry comes from `grafana.additionalDataSources` (deploy/observability/values/kube-prometheus-stack.yaml:78-84) and is rendered after the chart's Prometheus and Alertmanager sources (kube-prometheus-stack chart member `templates/grafana/configmaps-datasources.yaml`, lines 29-39 and 79-96, outside this working tree).
- **Target:** grafana
- **Writes:** no
- **Preconditions:** None; the source is provisioned at install.
- **Method:** GET /api/datasources/uid/loki
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none
- **Expected:** 200 with a JSON object whose `name` is `Loki`, `type` is `loki`, `uid` is `loki` and `access` is `proxy` (deploy/observability/values/kube-prometheus-stack.yaml:80-84; tests/observability/test_logs.py:176-177 checks `type` and `url`). Its `url` has scheme `http`, host `loki.monitoring.svc` and port `3100` (deploy/observability/values/kube-prometheus-stack.yaml:83)
- **Edge cases:**
  - The same request without an Authorization header: 401, and the body carries no data source fields, because the values configure no anonymous access (deploy/observability/values/kube-prometheus-stack.yaml:70-90) (unverified — confirm at run time)
  - GET `/api/datasources/uid/loki-qa-missing` with the same Basic auth: 404 (unverified — confirm at run time)
  - GET `/api/datasources` with the same Basic auth: 200 with an array that contains `Loki` (`uid` `loki`, `isDefault` `false` because the entry sets no default, and `readOnly` `true` because it is provisioned from a file), `Prometheus` (`uid` `prometheus`, `isDefault` `true`) and `Alertmanager` (`uid` `alertmanager`), so the added source kept the chart's sources and default (deploy/observability/values/kube-prometheus-stack.yaml:78-84) (unverified — confirm at run time)

### BE-02: The Loki data source health check reaches Loki
- **Area:** Grafana's health check for the `Loki` source, which queries the `loki` service in monitoring (deploy/observability/values/loki.yaml:3-6). Loki accepts requests without a tenant header (deploy/observability/values/loki.yaml:10), and the data source sets none (deploy/observability/values/kube-prometheus-stack.yaml:79-84).
- **Target:** grafana
- **Writes:** no
- **Preconditions:** None.
- **Method:** GET /api/datasources/uid/loki/health
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none
- **Expected:** 200 with `status` `OK` (tests/observability/test_logs.py:179-180)
- **Edge cases:**
  - GET `/api/datasources/proxy/uid/loki/loki/api/v1/status/buildinfo` with the same Basic auth: 200 with `version` `3.7.10`, the Loki release of the pinned chart 21.2.3 (platform/versions.env:16-19) (unverified — confirm at run time)
  - GET `/api/datasources/uid/prometheus/health` with the same Basic auth: 200 with `status` `OK`; the chart's Prometheus source still works next to Loki (docs/plans/2026-11-21-t17-logi-zdarzenia.md:17) (unverified — confirm at run time)
  - The health request without an Authorization header: 401, and Grafana runs no check (deploy/observability/values/kube-prometheus-stack.yaml:70-90) (unverified — confirm at run time)

### BE-03: A frontend WARNING line reaches Loki with Alloy's stream labels
- **Area:** Alloy's pod-log pipeline: discovery and relabelling (deploy/observability/values/alloy.yaml:19-58), file tailing (lines 60-68), CRI parsing, the `level` label and the dropped `filename` (lines 70-89), read through Grafana's Loki data source proxy. State row 1.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** Anonymously GET `http://localhost:8080/qa-$QA_TAG-missing` (target `frontend`): 404 with `detail` `Not Found`, because the frontend has no such route (services/frontend/src/frontend/app.py:94-102; .venv/lib/python3.13/site-packages/starlette/routing.py:633-634; .venv/lib/python3.13/site-packages/fastapi/exception_handlers.py:15-17). The frontend's request-log middleware writes one JSON line for it to stdout with `level` `WARNING`, `service` `frontend`, `route` `unmatched`, `status` 404 and `msg` `GET ` plus the request path (libs/observability/src/observability/__init__.py:53-66, 73, 103-130); uvicorn's access log is off (services/frontend/src/frontend/__main__.py:15), and Locust never requests this path (deploy/base/locust/locustfile.py:28-40). Send the main request within 10 minutes.
- **Method:** GET /api/datasources/proxy/uid/loki/loki/api/v1/query_range
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none; URL-encoded query parameters `query` = `{namespace="shop", container="frontend"} |= "qa-$QA_TAG-missing" | json | level="WARNING"`, `since` = `15m` and `limit` = `100`. While `data.result` is empty, repeat the request every 5 s for up to 120 s (tests/observability/test_logs.py:37, 84-91).
- **Expected:** 200 with `status` `success` and `data.resultType` `streams`; each stream has a `stream` label map and a `values` list whose items are pairs of a timestamp and the line (tests/observability/test_logs.py:76-81) (unverified — confirm at run time). At least one stream's labels include `namespace` `shop`, `container` `frontend`, a `pod` starting with `frontend-` and `stream` `stdout`, and have no `filename` key (deploy/observability/values/alloy.yaml:36-49, 73-74, 85-88; deploy/base/frontend/deployment.yaml:4, 30). The same labels include `level` `WARNING`, and the field that `| json` parses appears as `level_extracted` `WARNING` because `level` is already a stream label (deploy/observability/values/alloy.yaml:76-83; docs/plans/2026-11-21-t17-logi-zdarzenia.md:56) (unverified — confirm at run time). The line parses as JSON with `level` `WARNING`, `service` `frontend`, `route` `unmatched`, `status` 404 and a `msg` starting with `GET /qa-` (libs/observability/src/observability/__init__.py:53-66, 112-130)
- **Edge cases:**
  - `query` = `{namespace="shop", container="frontend", level="WARNING"} |= "qa-$QA_TAG-missing"`, with no `| json`: 200 with at least one stream, so `level` is a stream label set by Alloy and not only a parsed field (deploy/observability/values/alloy.yaml:76-83; tests/observability/test_logs.py:198-200 runs the same check for `ERROR`)
  - `query` = `{namespace="shop", container="frontend", level="ERROR"} |= "qa-$QA_TAG-missing"`: 200 with `status` `success` and an empty `data.result`, because the 404 was logged at `WARNING` (libs/observability/src/observability/__init__.py:112-118; deploy/observability/values/alloy.yaml:76-83)
  - The main request without an Authorization header: 401 with no `data` key in the body, so the host cannot read Loki without Grafana credentials (deploy/observability/values/kube-prometheus-stack.yaml:70-90) (unverified — confirm at run time)

### BE-04: An order placed through the frontend reaches Loki from the orders container at INFO
- **Area:** The acceptance criterion's stream `{namespace="shop", container="orders"}` (tests/observability/test_logs.py:32) and the frontend's `/order` route, collected by Alloy (deploy/observability/values/alloy.yaml:19-89) and read through Grafana's Loki data source proxy. State row 1.
- **Target:** grafana
- **Writes:** yes
- **Preconditions:** Anonymously POST `http://localhost:8080/order` (target `frontend`) with the JSON body `{"product_id": "kubek", "quantity": 1}`: 201 with the keys `id`, `product_id` (`kubek`), `quantity` (1) and `created_at` (services/frontend/src/frontend/app.py:62-66, 102-121). The frontend calls orders `POST /orders`, which stores the order and answers 201 (services/frontend/src/frontend/app.py:107-109; services/orders/src/orders/app.py:102-114). Each service's request-log middleware writes one INFO line: orders with `route` `/orders`, `status` 201 and `msg` `POST /orders`, the frontend with `route` `/order` and `status` 201 (libs/observability/src/observability/__init__.py:103-130). Send the main request within 10 minutes.
- **Method:** GET /api/datasources/proxy/uid/loki/loki/api/v1/query_range
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none; URL-encoded query parameters `query` = `{namespace="shop", container="orders"} | json | route="/orders" | status="201"`, `since` = `15m` and `limit` = `100`. While `data.result` is empty, repeat the request every 5 s for up to 120 s (tests/observability/test_logs.py:37, 84-91).
- **Expected:** 200 with `status` `success` (tests/observability/test_logs.py:76) (unverified — confirm at run time). At least one stream has the labels `namespace` `shop`, `container` `orders`, a `pod` starting with `orders-`, `level` `INFO` and `stream` `stdout`, and no `filename` (deploy/observability/values/alloy.yaml:36-49, 73-88; deploy/base/orders/deployment.yaml:4, 30). Its lines parse as JSON with `service` `orders`, `route` `/orders`, `status` 201 and `msg` `POST /orders` (libs/observability/src/observability/__init__.py:53-66, 112-130; services/orders/src/orders/__main__.py:9). Locust's orders add more entries to this result (docs/architektura.md:262); the tester's order guarantees at least one.
- **Edge cases:**
  - Anonymously POST `http://localhost:8080/order` with `{"product_id": "qa-missing", "quantity": 1}`: 404 with `detail` `unknown product`, and orders is not called (services/frontend/src/frontend/app.py:104-105). Then `query` = `{namespace="shop", container="frontend", level="WARNING"} | json | route="/order" | status="404"` with `since` = `15m`, repeating the query (never the POST) every 5 s for up to 120 s while `data.result` is empty (tests/observability/test_logs.py:37, 84-91): 200 with at least one stream whose lines have `route` `/order` and `status` 404. Locust orders only catalogue products, so the entry is the tester's (libs/observability/src/observability/__init__.py:103-118; deploy/base/locust/locustfile.py:14, 32-40)
  - The acceptance-criterion query `{namespace="shop", container="orders"} | json | level="ERROR"` with `since` = `15m`: 200 with `status` `success`, so Loki parses and runs it. Entries appear only while the `errors` fault runs, which is out of harness scope, so `data.result` may be empty (tests/observability/test_logs.py:32, 183-200) (unverified — confirm at run time)

### BE-05: Loki holds labels and namespaces only from Alloy's scope
- **Area:** The label set and namespace scope of the pod-log pipeline (deploy/observability/values/alloy.yaml:19-89), read through Loki's label endpoints behind Grafana's data source proxy. State rows 1-4.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** Anonymously GET `http://localhost:8080/` (target `frontend`): 200 with the five-product catalogue, logged at INFO with `route` `/` (services/frontend/src/frontend/app.py:45-54, 98-100; libs/observability/src/observability/__init__.py:112-130). Then GET `http://localhost:8080/qa-$QA_TAG-labels`: 404, logged at WARNING (libs/observability/src/observability/__init__.py:103-118). Send the requests below within 10 minutes, and repeat a request every 5 s for up to 120 s while a value it expects from these preconditions is missing (tests/observability/test_logs.py:37, 84-91).
- **Method:** GET /api/datasources/proxy/uid/loki/loki/api/v1/labels?since=15m
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none
- **Expected:** 200 with `status` `success` and a `data` array that includes `container`, `level`, `namespace`, `pod` and `stream` and does not include `filename` (deploy/observability/values/alloy.yaml:36-49, 73-88; docs/plans/2026-11-21-t17-logi-zdarzenia.md:434). The array also includes `service_name`, which Loki adds itself (docs/architektura.md:206) (unverified — confirm at run time)
- **Edge cases:**
  - GET `/api/datasources/proxy/uid/loki/loki/api/v1/label/namespace/values?since=72h`: 200 with a `data` array that includes `shop`, and every value is one of `aiops`, `intruder`, `loadgen` and `shop`; neither `monitoring` nor `kube-system` appears (state rows 3-4) (deploy/observability/values/alloy.yaml:22-24, 94; docs/plans/2026-11-21-t17-logi-zdarzenia.md:435)
  - GET `/api/datasources/proxy/uid/loki/loki/api/v1/query_range` with `query` = `{namespace=~"monitoring|kube-system"}`, `since` = `72h` and `limit` = `100`: 200 with `status` `success` and an empty `data.result`, although Alloy's own pods in monitoring run on the worker nodes it reads (state rows 3-4) (deploy/observability/values/alloy.yaml:22-24; docs/plans/2026-11-21-t17-logi-zdarzenia.md:431)
  - GET `/api/datasources/proxy/uid/loki/loki/api/v1/label/level/values?since=15m`: 200 with a `data` array that includes `INFO` and `WARNING` from the preconditions, and every value is one of the contract levels `DEBUG`, `INFO`, `WARNING` and `ERROR` (libs/observability/src/observability/__init__.py:40, 57; docs/architektura.md:186)
  - GET `/api/datasources/proxy/uid/loki/loki/api/v1/query_range` with `query` = `{namespace="loadgen", container="locust"}`, `since` = `1h` and `limit` = `100`: 200 with at least one stream, and no stream has a `level` label, because Locust logs its user-count changes as text, not JSON (state row 2) (docs/architektura.md:263; deploy/base/locust/deployment.yaml:44-51; deploy/observability/values/alloy.yaml:76) (unverified — confirm at run time)

### BE-06: Kubernetes events from the four namespaces are stored as JSON lines under `job="loki.source.kubernetes_events"`
- **Area:** `loki.source.kubernetes_events` (deploy/observability/values/alloy.yaml:91-101), which sends events straight to `loki.write` without the pod-log stages (line 96), read through Grafana's Loki data source proxy.
- **Target:** grafana
- **Writes:** no
- **Preconditions:** The harness cannot create a Kubernetes event: the kubelet and the controllers record one whenever a pod in shop, loadgen, aiops or intruder is scheduled, started, restarted or fails a probe, for example during `make deploy`, and Loki keeps entries for 72 h (deploy/observability/values/loki.yaml:25-30). If the main request returns an empty `data.result`, report `NEED_INFO kind=fixture` for "a Kubernetes event in shop, loadgen, aiops or intruder within the last 72 h".
- **Method:** GET /api/datasources/proxy/uid/loki/loki/api/v1/query_range
- **Headers:** Authorization: Basic built from user name `$QA_GRAFANA_ADMIN_EMAIL` and password `$QA_GRAFANA_ADMIN_PASSWORD`, passed to curl as a config `user` line on stdin, never on argv
- **Payload:** none; URL-encoded query parameters `query` = `{job="loki.source.kubernetes_events"}`, `since` = `72h` and `limit` = `100`
- **Expected:** 200 with `status` `success` and at least one stream (unverified — confirm at run time). Every stream has `job` `loki.source.kubernetes_events`, a `namespace` that is one of `aiops`, `intruder`, `loadgen` and `shop`, and an `instance` key, and none has `pod`, `container`, `stream` or `level`, because events skip `loki.process "pods"` (deploy/observability/values/alloy.yaml:91-101; docs/architektura.md:207) (unverified — confirm at run time). Each line parses as JSON with the keys `kind`, `name`, `reason`, `type` and `msg`, and `type` is `Normal` or `Warning` (deploy/observability/values/alloy.yaml:95; docs/architektura.md:207) (unverified — confirm at run time)
- **Edge cases:**
  - `query` = `{job="loki.source.kubernetes_events", namespace=~"monitoring|kube-system|default"}` with `since` = `72h`: 200 with `status` `success` and an empty `data.result`, because Alloy watches events only in the four namespaces (deploy/observability/values/alloy.yaml:94)
  - GET `/api/datasources/proxy/uid/loki/loki/api/v1/label/job/values?since=72h`: 200 with a `data` array that includes `loki.source.kubernetes_events` (deploy/observability/values/alloy.yaml:91-93; docs/architektura.md:207) (unverified — confirm at run time)

## Out of harness scope
- Acceptance criterion 1 as specified: after `fault-runner fault errors --seconds 30 --param ratio=1` with `fault-runner spike`, `{namespace="shop", container="orders"} | json | level="ERROR"` returns orders entries, among them a 500 on route `/orders`, and the selector `{namespace="shop", container="orders", level="ERROR"}` returns entries too (tests/observability/test_logs.py:183-200; docs/plans/2026-11-21-t17-logi-zdarzenia.md:6) — the fault starts only through `kubectl exec` into `loadgen/fault-runner`, whose in-cluster requests to orders' `/faults/*` carry `X-Fault-Token` (docs/architektura.md:254; deploy/base/fault-runner/deployment.yaml:18-21); BE-03 and BE-04 run the same query pipeline on entries the harness can create.
- Acceptance criterion 2: a `BackOff` Warning event for the orders `Pod` after two `fault-runner fault crash` within 10 min, with a `msg` containing `Back-off restarting failed container orders`, and the PodRestarts e-mail in Mailpit that the restarts trigger (tests/observability/test_logs.py:7-8, 203-222; docs/plans/2026-11-21-t17-logi-zdarzenia.md:7, 25) — crashing orders needs `kubectl exec` into fault-runner.
- Each Kubernetes event is stored once, and every Alloy pod sees 2 cluster peers (docs/plans/2026-11-21-t17-logi-zdarzenia.md:815-826; deploy/observability/values/alloy.yaml:98-100, 108-110) — this needs `kubectl create` of a test Event and Alloy's port 12345 through the API server proxy, neither of which is a configured target.
- Loki's shape: the rendered objects (no gateway, memcached, canary or helm test; a ClusterRole with empty rules), pod `loki-0` 1/1 Running and PVC `storage-loki-0` Bound with 5Gi on `standard` (docs/plans/2026-11-21-t17-logi-zdarzenia.md:211-212, 214; deploy/observability/values/loki.yaml:6, 35-40, 56-76) — these are helm template, yq and kubectl checks; FE-01 reads the running configuration through Grafana.
- Deletion of entries older than 72 h by the compactor (deploy/observability/values/loki.yaml:25-30) — this needs more than 72 h of wall-clock time.
- Alloy's shape and hardening: 13 rendered objects with no ClusterRole and no PodLogs CRD, DaemonSet `alloy` 2/2 ready on both workers with 0 restarts, identity `uid=473(alloy) gid=0(root)`, a read-only root filesystem without capabilities, `/var/log` as the only host path, and log files read only for pods on the instance's own node (docs/plans/2026-11-21-t17-logi-zdarzenia.md:410-436; deploy/observability/values/alloy.yaml:10-11, 26-30, 113-145) — these are helm, kubectl and `kubectl exec` checks.
- Alloy's RBAC: `sa:monitoring/alloy` may list pods and watch events in the four namespaces, and may not list secrets in shop or cluster-wide, configmaps in shop or pods in kube-system (tests/security/test_rbac.py:105-115; deploy/observability/values/alloy.yaml:147-154) — this is `kubectl auth can-i` impersonation against the Kubernetes API, which is not a configured target.
- Residual risk R1: any pod in the cluster can query or push entries at `loki.monitoring.svc:3100` without credentials (docs/bezpieczenstwo.md:111; BLK-01) — this needs a client pod inside the cluster.
- `make observability` installs Loki and then Alloy, each pinned by version and digest, after kube-prometheus-stack; a repeated `make up` changes no pod in monitoring; a fresh `make up` passes `tests/observability` and `make test-security` (Makefile:115-127; platform/versions.env:15-22; docs/plans/2026-11-21-t17-logi-zdarzenia.md:806-847) — these are make, helm and pytest runs on the host.
- `make lint`, `make unit`, `make manifests`, `make trivy-config` and the collected test counts (docs/plans/2026-11-21-t17-logi-zdarzenia.md:803-805) — these are CLI runs with no browser or HTTP surface.
- README, docs/architektura.md and docs/bezpieczenstwo.md describe the T17 contract and risks (README.md:41, 54, 78, 128-133; docs/architektura.md:13-14, 24, 93, 204-211; docs/bezpieczenstwo.md:88, 111-112) — this is static text with no runtime behaviour.
