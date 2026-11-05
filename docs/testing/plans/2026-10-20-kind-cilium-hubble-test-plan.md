# Test Plan: T03 kind cluster with Cilium and Hubble (Hubble UI)

## Source
- Type: last 2 commits (`git diff HEAD~2...HEAD`)
- Base: main
- Date: 2026-10-20
- Branch: delivery/t03-kind-cilium-hubble
- Head: 0ae89422479d20e1863ec4dc534f9d27287b9f8d

## Changes Summary

Both commits name the delivery plan `docs/plans/2026-10-20-t03-kind-cilium-hubble.md` in their own `Delivery-Plan:` trailer. The path was accepted: it is repository-relative, has no symlinked component and is a regular file inside the repository root. No trailer was rejected. The delivered code matches the plan's file contents (Task 1) and edits (Task 2).

- `1b1de3e8` "feat(platform): klaster kind z Cilium i Hubble (make cluster, make hubble-ui)", Delivery-Task-Title "Konfiguracja kind i Cilium oraz cele make cluster i hubble-ui", maps to plan Task 1:
  - `platform/versions.env`: Cilium chart 1.20.3 and prometheus-operator-crds 32.0.1.
  - `platform/kind/cluster.yaml`: 1 control-plane and 2 workers on `kindest/node:v1.36.4`, default CNI disabled, NodePorts 30080/30300/30825 mapped to 127.0.0.1:8080/3000/8025.
  - `platform/cilium/values.yaml`: Hubble, Relay and UI enabled; agent, operator and Hubble metrics with ServiceMonitors; six Hubble metrics with source/destination `labelsContext`.
  - `Makefile`: targets `cluster` (idempotent kind creation plus two `helm upgrade --install`) and `hubble-ui` (`cilium hubble ui` port-forward on localhost:12000).
  - `platform/.gitkeep`: removed.
- `0ae89422` "docs: klaster lokalny i kontrakt metryk Cilium/Hubble (T03)", Delivery-Task-Title "Dokumentacja klastra lokalnego i kontraktu Cilium/Hubble", maps to plan Task 2: `docs/architektura.md` (node image, Kubernetes 1.36 rationale, cluster and context names, Cilium/Hubble metrics contract), `docs/karta-projektu.md` (Kubernetes 1.36 row) and `README.md` ("Klaster lokalny" section).

Classification:
- FE and BE: the Hubble keys of `platform/cilium/values.yaml` (lines 17-22: `hubble.enabled`, `hubble.relay.enabled`, `hubble.ui.enabled`) deploy the browser UI and its HTTP surface. `make hubble-ui` (Makefile:38-40) serves them on target `hubble_ui`. Covered by FE-01, FE-02 and BE-01.
- Neither: the other values keys (IPAM, image pull policy, Prometheus/ServiceMonitor, Hubble metrics), `platform/kind/cluster.yaml`, `platform/versions.env`, the `cluster` target, `platform/.gitkeep`, `README.md`, `docs/architektura.md` and `docs/karta-projektu.md`. These are infrastructure config, tooling and documentation. Their verifiable effects are listed under Out of harness scope.

Intended contract, from the delivery plan's Context and Verification:
- Success path:
  - `make cluster` exits 0 with three `Ready` nodes on `v1.36.4`, both Helm releases `deployed` and `cilium status` OK (plan lines 214-216 and 227).
  - A second run prints `Klaster secure-k8s-aiops już istnieje.` and recreates no pod (lines 217-226).
  - Hubble lists flows, for example `kube-system/coredns-…` with verdict `FORWARDED` (line 228).
  - `cilium connectivity test` passes (line 229).
  - The ServiceMonitors, the `hubble-metrics` entries and `hubble_drop_total{reason="POLICY_DENIED"}` series exist (lines 230-240).
  - While `make hubble-ui` runs, `GET /` on localhost:12000 returns `200` (line 241).
- Declared error paths. Each one is a CLI exit path with no HTTP status:
  - A taken host port 8080, 3000 or 8025 makes `kind create cluster` fail with `address already in use` or `port is already allocated` (line 254; README.md:40).
  - If the Cilium install runs past `--timeout 10m`, rerun `make cluster` (line 255; Makefile:34).
  - Connectivity tests that need internet access are skipped with a note (line 256).
  - If no `POLICY_DENIED` series exists, check that `all-ingress-deny-knp` ran (line 257).
- Inside the browser/HTTP harness, this leaves the Hubble UI on `hubble_ui`: the app is served (`GET /` returns 200) and it shows `kube-system` flows.

Evidence sources:
- The Cilium chart 1.20.3 pinned by `platform/versions.env:3` was read from the Helm OCI cache `~/.cache/helm/content/08/0805a5273118c436c9772bb9566d87ec558d8b25cc2ce5dc32918ecdd36f2c7c.chart`. A reference `cilium-1.20.3/<path>:<line>` names archive member `cilium/<path>`; read it with `tar -xzOf <archive> cilium/<path>`. The chart is outside this working tree, so these references are context only, and expectations that rest on a chart template carry the unverified tag.
- The Hubble UI frontend and backend code (images `quay.io/cilium/hubble-ui` and `quay.io/cilium/hubble-ui-backend` v0.13.6, cilium-1.20.3/values.yaml lines 2049-2051 and 2082-2084) is not on disk. UI rendering assertions therefore carry an unverified tag.
- `cilium hubble ui --help` from the installed cilium-cli 0.20.1 shows `--port-forward` default 12000 and `--open-browser` default true.

## Blockers / Findings

None found.

## Users

No users are declared. The Hubble UI has no login: its nginx server block has no auth directives (cilium-1.20.3/templates/hubble-ui/_nginx.tpl:2-49), and it is reached through the local `make hubble-ui` port-forward (Makefile:38-40). Every scenario runs anonymously.

## Detected Tools
- Playwright MCP: available
- HTTP client: curl (httpie unavailable); jq and perl JSON::PP available for response inspection
- Store clients: psql and sqlite3 available; mysql and redis-cli unavailable. No store is configured and no scenario needs a State Check.

## FE Test Scenarios

State combinations: three Helm flags drive the Hubble UI on `hubble_ui`, and `platform/cilium/values.yaml:17-22` sets all three to `true`. Chart defaults are `hubble.enabled` true, `hubble.relay.enabled` false and `hubble.ui.enabled` false (cilium-1.20.3/values.yaml lines 1450, 1763 and 2006). The rows below apply to FE-01, FE-02 and BE-01.

| `hubble.enabled` | `hubble.relay.enabled` | `hubble.ui.enabled` | Classification | Disposition |
|---|---|---|---|---|
| on | on | on | real: the configured state | FE-01, FE-02, BE-01 |
| on | on | off | real: the chart renders but has no `hubble-ui` Service (cilium-1.20.3/templates/hubble-ui/service.yaml:1), so `make hubble-ui` has nothing to forward | out of harness scope: deploy-time Helm value fixed by platform/cilium/values.yaml:21-22; changing it needs `helm upgrade`, which browser/HTTP/DB cannot run |
| on | off | on | impossible: rendering fails with "Hubble UI requires .Values.hubble.relay.enabled=true" (cilium-1.20.3/templates/validate.yaml:59-61); `hubble.ui.standalone.enabled` stays false (cilium-1.20.3/values.yaml:2012) | — |
| on | off | off | real: chart default for Relay and UI | out of harness scope: same reason as row 2 |
| off | on | on | impossible: "Hubble Relay requires .Values.hubble.enabled=true" (cilium-1.20.3/templates/validate.yaml:69-71) | — |
| off | on | off | impossible: cilium-1.20.3/templates/validate.yaml:69-71 | — |
| off | off | on | impossible: cilium-1.20.3/templates/validate.yaml:59-61 | — |
| off | off | off | real: Hubble disabled, nothing to forward | out of harness scope: same reason as row 2 |

The Prometheus/ServiceMonitor and Hubble metrics flags (platform/cilium/values.yaml:8-16 and 33-34) only produce Kubernetes objects and agent metrics outside every configured target. They are listed under Out of harness scope.

### FE-01: Hubble UI start page loads and offers the `kube-system` namespace
- **Area:** Hubble UI start page: hubble-ui v0.13.6 frontend and backend, deployed by `hubble.ui.enabled` (platform/cilium/values.yaml:21-22)
- **Target:** hubble_ui
- **Writes:** no
- **Preconditions:** None. The UI has no login and needs no test data. The namespace list comes from the hubble-ui backend, whose ClusterRole may get, list and watch namespaces (cilium-1.20.3/templates/hubble-ui/clusterrole.yaml:17-29).
- **Steps:**
  1. Open `/` in the browser.
  2. Wait up to 30 s for the Hubble UI to finish loading: no spinner, and the top bar is visible.
  3. Click the namespace selector dropdown in the top-left corner of the top bar.
- **Expected:** The Hubble UI app renders with its top bar and namespace selector, not an nginx error page or a blank page. The opened namespace selector lists `kube-system`, the namespace where `make cluster` installs Cilium and Hubble (Makefile:33) (unverified — confirm at run time)
- **Edge cases:**
  - Open `/?namespace=kube-system` directly: the UI opens with `kube-system` already selected and shows its service map without using the dropdown (unverified — confirm at run time)
  - Open `/qa-no-such-page`: the Hubble UI app renders with its top bar, not nginx's `404 Not Found` page. nginx answers unknown paths with `/index.html` through the `try_files` fallback in the Cilium 1.20.3 chart's `templates/hubble-ui/_nginx.tpl`, and from a single-segment path the page's relative URLs still resolve from `/` (unverified — confirm at run time)
  - Open `/?namespace=qa-no-such-namespace`: the UI stays responsive, no workload cards or flow rows appear for that namespace, and the namespace selector still opens and lists `kube-system` (unverified — confirm at run time)

### FE-02: `kube-system` flows appear in the service map and flows table
- **Area:** Hubble UI namespace view (service map and flows table), fed by Hubble Relay through `hubble.relay.enabled` (platform/cilium/values.yaml:19-20)
- **Target:** hubble_ui
- **Writes:** no
- **Preconditions:** None, and no test data is needed because `kube-system` carries continuous traffic of its own. Kubelet probes the hubble-ui frontend on `/healthz` and `/` (cilium-1.20.3/templates/hubble-ui/deployment.yaml:81-88). While the page is open, the UI backend reads flows from `hubble-relay:80` (cilium-1.20.3/templates/hubble-ui/deployment.yaml:126-128).
- **Steps:**
  1. Open `/` in the browser.
  2. In the namespace selector dropdown in the top-left corner, choose `kube-system`.
  3. Wait up to 60 s for the service map and the flows table below it to fill.
  4. Click the first row of the flows table.
- **Expected:** The service map shows at least one card for a `kube-system` workload, for example `hubble-ui`, `hubble-relay` or CoreDNS (`kube-dns`). The flows table lists at least one flow with verdict `forwarded`. Clicking a row opens a details panel that names the flow's source, destination and verdict (platform/cilium/values.yaml:19-22) (unverified — confirm at run time)
- **Edge cases:**
  - With `kube-system` selected, set the verdict filter in the top bar to "Dropped": every remaining row has verdict `dropped`, or the table is empty. No `forwarded` row stays listed (unverified — confirm at run time)
  - Choose `default` in the namespace selector: the map no longer shows `hubble-ui` or `hubble-relay` cards. Both run in `kube-system`, and nothing in `default` talks to them (unverified — confirm at run time)
  - Reload the page with `kube-system` selected: the UI returns with `kube-system` still selected and lists flow rows again (unverified — confirm at run time)

## BE Test Scenarios

### BE-01: Hubble UI frontend serves the app, its liveness endpoint and the backend proxy
- **Area:** hubble-ui frontend nginx on port 8081 behind Service `hubble-ui` port 80 (cilium-1.20.3/templates/hubble-ui/service.yaml:33-36), reached through `make hubble-ui` (Makefile:38-40)
- **Target:** hubble_ui
- **Writes:** no
- **Preconditions:** None. Requests are anonymous and carry no Authorization header, because the nginx server block has no auth directives (cilium-1.20.3/templates/hubble-ui/_nginx.tpl:2-49).
- **Method:** GET /
- **Headers:** none
- **Payload:** none
- **Expected:** 200 with a `Content-Type` header that starts with `text/html`. qa-redact withholds the non-JSON HTML body, so record its withheld byte count and the `Content-Length` header for the edge cases. nginx serves the Hubble UI `index.html` through `index index.html` and `try_files $uri $uri/ /index.html /index.html` in the Cilium 1.20.3 chart's `templates/hubble-ui/_nginx.tpl`, a template outside this working tree (unverified — confirm at run time)
- **Edge cases:**
  - GET `/healthz`: 200 with `Content-Length: 2` and a 2-byte withheld body, from `return 200 'ok'` in the chart template's `location /healthz` (unverified — confirm at run time)
  - GET `/qa-no-such-page/deep/link`: 200, not 404, with a `Content-Type` that starts with `text/html` and the same withheld byte count and `Content-Length` as `GET /`, because the chart template's `try_files` falls back to `/index.html` (unverified — confirm at run time)
  - GET `/api/`: the chart template's `location /api` proxies the request to the hubble-ui backend on port 8090, which answers. The status is neither 502 nor 504; the exact status is not pinned. Its `Content-Type` or `Content-Length` differs from `GET /`'s, and a missing header counts as different (unverified — confirm at run time)

## Out of harness scope
- `make cluster` exits 0 with three `Ready` nodes on `v1.36.4` and both Helm releases `deployed`, and its rerun prints `Klaster secure-k8s-aiops już istnieje.` without recreating any kube-system pod (Makefile:22-36). These are make/kind/helm/kubectl CLI runs, outside browser/HTTP/DB.
- `make cluster` failure paths: a taken host port 8080, 3000 or 8025 makes `kind create cluster` fail with `address already in use` or `port is already allocated` (Makefile:26; README.md:40; docs/plans/2026-10-20-t03-kind-cilium-hubble.md:254), and a Cilium `helm upgrade` that runs past `--timeout 10m` fails `make cluster`, which is then rerun (Makefile:34; docs/plans/2026-10-20-t03-kind-cilium-hubble.md:255). These are kind and helm CLI failures with no browser or HTTP surface.
- `cilium status --wait` reports OK for the agent, operator, Envoy and Hubble Relay (Makefile:35). This is cilium CLI output, not served on a target.
- `hubble observe --last 20` lists flows. This is hubble CLI output; FE-02 checks the same flows through the UI.
- `cilium connectivity test` passes, including the `POLICY_DENIED` drops of `all-ingress-deny-knp`. This CLI suite deploys its own pods and NetworkPolicies, which the harness cannot do.
- Host port mappings 30080 to 127.0.0.1:8080, 30300 to 127.0.0.1:3000 and 30825 to 127.0.0.1:8025 (platform/kind/cluster.yaml:12-24). These are read with `docker port`; nothing is deployed behind these NodePorts yet, and they are not configured targets.
- ServiceMonitors `cilium-agent` (9962), `cilium-operator` (9963) and `hubble` (9965) in `kube-system`, and six `hubble-metrics` entries in ConfigMap `cilium-config` (platform/cilium/values.yaml:8-16 and 23-34). These are Kubernetes API objects, not on a configured target.
- `hubble_drop_total{reason="POLICY_DENIED"}` with non-empty `source_workload` and `destination_workload` labels on agent port 9965 (docs/architektura.md:78; docs/plans/2026-10-20-t03-kind-cilium-hubble.md:240). No configured or repository-documented host origin exposes agent port 9965 (the delivery plan reads it with `kubectl get --raw`, docs/plans/2026-10-20-t03-kind-cilium-hubble.md:236), and the series needs the connectivity test's NetworkPolicy drops.
- The documentation updates (README.md:33-40, docs/architektura.md lines 9, 25, 40 and 78, docs/karta-projektu.md:113) agree with the `platform/` files. This is static text with no runtime behaviour to observe.
