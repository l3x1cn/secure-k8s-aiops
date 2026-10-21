# Test Plan: T03 security fixes (Hubble NetworkPolicy, Helm charts pinned by digest, vendor-image risk)

## Source
- Type: last 3 commits (`git diff HEAD~3...HEAD`)
- Base: main
- Date: 2026-10-21
- Branch: delivery/t03-kind-cilium-hubble
- Head: 7548e06fa9123948433d1b446196e0137f04f69b

## Changes Summary

All three commits name the delivery plan `docs/plans/2026-10-21-t03-sec-fixes.md` in their own `Delivery-Plan:` trailer. The path was accepted: it is repository-relative, has no `..` segment and no symlinked component, and resolves to a regular file inside the repository root. No trailer was rejected. The delivered files match the plan's Tasks 1-3.

- `1a707132` "fix(platform): NetworkPolicy ogranicza dostęp do Hubble Relay i Hubble UI", Delivery-Task-Title "NetworkPolicy dla Hubble Relay i Hubble UI (SEC-001)", maps to plan Task 1:
  - `platform/cilium/hubble-networkpolicy.yaml` (new): NetworkPolicy `kube-system/hubble-relay-ui-ingress` selects pods whose `k8s-app` is `hubble-relay` or `hubble-ui` (lines 10-14), restricts Ingress only (line 15) and admits only pods labelled `k8s-app: hubble-ui` on TCP 4245 (lines 16-23).
  - `Makefile`: `make cluster` applies the policy after the Cilium Helm release and before `cilium status` (line 36; comment line 22).
  - `docs/architektura.md:76`: the policy, host access through `make hubble-ui` and `make hubble-relay`, and the residual risk of agent and operator metrics on ports 9962, 9963 and 9965.
- `10271f1a` "fix(platform): instalacja chartów Helm po digeście", Delivery-Task-Title "Charty Helm przypięte digestem (SEC-002)", maps to plan Task 2:
  - `platform/versions.env:3,5,7`: `CILIUM_CHART_DIGEST` and `PROMETHEUS_OPERATOR_CRDS_CHART_DIGEST`.
  - `Makefile:20,29,32`: both `helm upgrade --install` calls install `<chart>@<digest>` and keep `--version`.
  - `docs/architektura.md:23`: the chart pinning rule.
- `7548e06f` "docs: zaakceptowane ryzyko podatności w obrazach Cilium i kindest/node", Delivery-Task-Title "Ryzyko podatności w obrazach dostawców (SEC-003)", maps to plan Task 3: `docs/architektura.md:27`, the accepted risk of HIGH/CRITICAL CVEs in vendor images.

No automated tests cover these files; the delivery plan defers CI to T06 (docs/plans/2026-10-21-t03-sec-fixes.md:17).

Classification:
- FE and BE: `platform/cilium/hubble-networkpolicy.yaml`. It decides which clients reach the Hubble UI pod, which serves the browser UI and its HTTP surface on target `hubble_ui` through `make hubble-ui` (Makefile:41-43), and the Hubble Relay pod, the UI's only data source. Covered by FE-01 and BE-01.
- Neither: `Makefile`, `platform/versions.env` and `docs/architektura.md`. These are repository tooling, install configuration and documentation. Their verifiable effects are listed under Out of harness scope.

Intended contract, from the delivery plan's Tasks and Verification (`docs/plans/2026-10-21-t03-sec-fixes.md`):
- Success paths:
  - `make cluster` exits 0, prints `networkpolicy.networking.k8s.io/hubble-relay-ui-ingress` with `created`, `configured` or `unchanged`, and leaves both Helm releases `deployed` (line 133). A rerun prints `Klaster secure-k8s-aiops już istnieje.` and `unchanged` and recreates no kube-system pod (line 134). `make -n cluster` shows the apply between `helm upgrade --install cilium` and `cilium status` (line 73) and both chart references with an `@sha256:` digest plus `--version` (line 105).
  - Kubelet probes keep `hubble-relay` and `hubble-ui` Ready after `rollout restart` (line 136), and `cilium status --wait` reports OK (line 137).
  - Allowed path: Hubble lists `hubble-ui` → `hubble-relay` flows on `:4245` with `FORWARDED` and none with `DROPPED` (line 140).
  - Host access: while `make hubble-ui` runs, `GET /` on localhost:12000 returns `200` (line 152).
  - The full `cilium connectivity test` passes (line 153). The SEC-003 paragraph sits between the Kubernetes 1.36 paragraph and `## Namespace'y i Pod Security` (line 119).
- Declared error paths. Each one is a CLI exit path with no HTTP status:
  - From a pod outside `hubble-ui`, curl to the `hubble-ui` and `hubble-relay` Services times out (exit 28), and Hubble shows `DROPPED` (`Policy denied`) to `hubble-ui` port 8081 and `hubble-relay` port 4245. The Kubernetes API and the agent metrics on the node IP port 9965 stay reachable (exit 0), which is the residual risk in `docs/architektura.md:76` (line 151).
  - No pod reaches Hubble UI, `hubble-ui` pods included. The policy's comment says Relay admits only Hubble UI and the UI admits nothing (`do UI nic`; line 31, delivered as platform/cilium/hubble-networkpolicy.yaml:2), the architecture paragraph says the policy admits no pod traffic into Hubble UI (line 70, delivered as docs/architektura.md:76), and the SEC-001 remediation asks for no ingress to `hubble-ui` (docs/reviews/2026-10-21-delivery-t03-kind-cilium-hubble.md:28). The delivered policy admits `hubble-ui` → `hubble-ui` on TCP 4245, so this path cannot return its declared result: BLK-01.
  - A chart digest that the version tag does not point to makes `make cluster` exit non-zero with `chart reference digest mismatch`, and the Cilium release keeps its REVISION (lines 11 and 135).
  - Contingencies: a registry tag moved since 2026-10-21 (line 157), Helm rejecting `@digest` together with `--version` (line 158), probes, the UI → Relay path or a port-forward failing under the policy (line 159), and connectivity-test failures (line 160).
- Inside the browser/HTTP harness this leaves the Hubble UI on `hubble_ui`: the UI → Relay path on TCP 4245 (FE-01) and host access to the UI pod (BE-01, FE-01).
- Coverage limit: FE-01 and BE-01 check only paths the policy must keep open, so they also pass when no policy is applied. Delivery Verification steps 2 and 3 check that the policy is applied, and step 8 checks its deny paths from a pod outside `hubble-ui` through both Services (state rows 5 and 8). No delivery step checks state rows 2, 4, 6 and 7, and state row 3 is BLK-01. All of these are listed under Out of harness scope.

Evidence sources:
- Cilium chart 1.20.3: the Helm cache entry for the pinned `CILIUM_CHART_DIGEST` (platform/versions.env:5), `~/.cache/helm/content/e8/e84f73cc9edcb0d00306ecee57a56f20bb32dddad77c8cef3af62d844ec8adea.chart`, byte-identical to the archive the 2026-10-20 plan read. Chart references in this plan name an archive member and its lines, for example chart member `cilium/values.yaml`, line 1874; read a member with `tar -xzOf <archive> <member>`. The chart is outside this working tree, so these references are context, not `(path:line)` citations, and expectations that rest on a template carry the unverified tag. Facts used:
  - Relay pods carry `k8s-app: hubble-relay` and listen on container port `grpc`, which is `hubble.relay.listenPort` `"4245"`; their gRPC probes use port 4222 (chart members `cilium/templates/hubble-relay/deployment.yaml`, lines 44 and 83-122; `cilium/templates/_extensions.tpl`, lines 80-82; `cilium/values.yaml`, line 1874).
  - Service `hubble-relay` maps port 80 to `grpc` while `hubble.relay.tls.server.enabled` is false (chart members `cilium/templates/hubble-relay/service.yaml`, lines 28-35; `cilium/templates/_extensions.tpl`, lines 84-86; `cilium/values.yaml`, line 1895).
  - Hubble UI pods carry `k8s-app: hubble-ui`. The frontend serves port 8081 with liveness probe `/healthz` and readiness probe `/`, and the backend on port 8090 reads from `FLOWS_API_ADDR=hubble-relay:80` (chart member `cilium/templates/hubble-ui/deployment.yaml`, lines 43, 74-88 and 127-135). Service `hubble-ui` maps port 80 to 8081 (chart member `cilium/templates/hubble-ui/service.yaml`, lines 33-36).
  - Relay metrics are disabled (chart member `cilium/values.yaml`, lines 1943-1944), so no scraper needs a rule in this policy.
- Hubble UI v0.13.6 (chart member `cilium/values.yaml`, lines 2049-2051 and 2082-2084): its code is not on disk. Upstream tag `v0.13.6` was read for UI names only, so UI assertions carry the unverified tag:
  - The flows table shows the columns `Source Identity`, `Destination Identity`, `Destination Port`, `L7 info`, `Verdict` and `Timestamp` by default (`src/components/FlowsTable/general.ts`). The verdict filter offers `Any verdict`, `Forwarded`, `Dropped` and `Audit` (`src/components/TopBar/VerdictFilterDropdown.tsx`).
  - The connection indicator at the right end of the top bar shows a flow rate in `flows/s` and the count of available and total nodes, for example `3/3 nodes`. Both come from Relay's `ServerStatus` and `GetNodes`, which the UI backend polls every 5 s over its Relay connection (`src/components/TopBar/ConnectionIndicator.tsx`; `backend/internal/statuschecker/status_checker.go`; `backend/internal/apiserver/control_stream.go`).
  - With a namespace selected, the UI lists only non-reply flows whose source or destination pod is in that namespace (`src/factories/proto/index.ts`).

## Blockers / Findings

### BLK-01: `hubble-relay-ui-ingress` admits `hubble-ui` → `hubble-ui` on TCP 4245, contrary to docs/architektura.md:76 — `(platform/cilium/hubble-networkpolicy.yaml:10-23)`
- **Impact on testing:** The single ingress rule (platform/cilium/hubble-networkpolicy.yaml:16-23) applies to every pod the policy selects, `hubble-ui` included (platform/cilium/hubble-networkpolicy.yaml:10-14). The policy's own comment (platform/cilium/hubble-networkpolicy.yaml:2), docs/architektura.md:76 and the SEC-001 remediation (docs/reviews/2026-10-21-delivery-t03-kind-cilium-hubble.md:28) say that no pod may reach Hubble UI. No FE or BE scenario exercises this path (state row 3), so no scenario result depends on it. An in-cluster check from one `hubble-ui` pod to another on TCP 4245 sees the connection admitted and then refused, because no `hubble-ui` container listens on 4245, instead of the `Policy denied` drop the documented contract requires.
- **Remediation (human Setup prerequisite):** None before this run, because no scenario depends on state row 3. The delivery plan prescribes this policy body next to the contradicting comment and paragraph (docs/plans/2026-10-21-t03-sec-fixes.md:31, 39-52, 70). To meet the documented contract, split the policy in two: one selecting `k8s-app: hubble-relay` with the current ingress rule, and one selecting `k8s-app: hubble-ui` with `policyTypes: [Ingress]` and no ingress rules. Otherwise narrow the comment at platform/cilium/hubble-networkpolicy.yaml:2 and docs/architektura.md:76 to what the policy enforces.
- **Blocks:** none; no scenario is blocked by BLK-01.

## Users

No users are declared. Neither the Hubble UI nor Hubble Relay has a login: the UI's nginx server block has no auth directives (Cilium 1.20.3 chart member `cilium/templates/hubble-ui/_nginx.tpl`, lines 2-49, outside this working tree), and this change restricts pod ingress without adding authentication (platform/cilium/hubble-networkpolicy.yaml:1-3). Every scenario runs anonymously from the host through `make hubble-ui` (Makefile:41-43).

## Detected Tools
- Playwright MCP: available
- HTTP client: curl (httpie unavailable); jq and perl JSON::PP available for response inspection
- Store clients: psql and sqlite3 available; mysql and redis-cli unavailable. No store is configured and no scenario needs a State Check.

## FE Test Scenarios

State combinations: `hubble-relay-ui-ingress` decides ingress to the pods it selects from three inputs: the connection's source, the destination pod and the destination port (platform/cilium/hubble-networkpolicy.yaml:10-23). Host-side traffic, meaning kubelet probes and the `make hubble-ui` and `make hubble-relay` port-forwards, stays open by design (platform/cilium/hubble-networkpolicy.yaml:3; docs/plans/2026-10-21-t03-sec-fixes.md:9). The full 3 × 2 × 2 product is below and applies to FE-01 and BE-01. Every row is real, because no invariant rules a combination out.

| # | Source | Destination pod | Port | Policy outcome | Disposition |
|---|---|---|---|---|---|
| 1 | `hubble-ui` pod | `hubble-relay` | TCP 4245 | admitted by the only ingress rule; this is the UI backend's flow and status stream (`hubble-relay:80` → `grpc` 4245) | FE-01 |
| 2 | `hubble-ui` pod | `hubble-relay` | other, for example probe port 4222 | denied: the port is not in the rule | out of harness scope — the client must run inside a `hubble-ui` pod, and browser/HTTP reach the cluster only from the host |
| 3 | `hubble-ui` pod | `hubble-ui` | TCP 4245 | admitted, because the rule covers both selected pods, but no `hubble-ui` container listens on 4245 (frontend 8081, backend 8090), so the connection is refused, not dropped | BLK-01: the documented contract admits no pod traffic into Hubble UI; out of harness scope for the same reason as row 2 |
| 4 | `hubble-ui` pod | `hubble-ui` | other (8081, 8090) | denied | out of harness scope — same reason as row 2 |
| 5 | any other pod | `hubble-relay` | TCP 4245 | denied; this is the SEC-001 threat of a compromised pod running `hubble observe --server hubble-relay.kube-system.svc:80` | out of harness scope — needs a client pod inside the cluster; delivery Verification step 8 covers it |
| 6 | any other pod | `hubble-relay` | other | denied | out of harness scope — needs a client pod inside the cluster; no delivery Verification step targets this port |
| 7 | any other pod | `hubble-ui` | TCP 4245 | denied | out of harness scope — needs a client pod inside the cluster; no delivery Verification step targets this port |
| 8 | any other pod | `hubble-ui` | other (8081 behind Service `hubble-ui` port 80) | denied | out of harness scope — same reason as row 5 |
| 9 | host side | `hubble-relay` | TCP 4245 | open: the `make hubble-relay` port-forward for `hubble observe` | out of harness scope — localhost:4245 speaks gRPC and is not a configured target; delivery Verification step 7 covers it |
| 10 | host side | `hubble-relay` | other (kubelet gRPC probes on 4222) | open | out of harness scope — probe results are pod conditions read with kubectl; delivery Verification step 5 covers them |
| 11 | host side | `hubble-ui` | TCP 4245 | open, but nothing listens on 4245 | out of harness scope — `make hubble-ui` forwards localhost:12000 only to the UI's port 8081 |
| 12 | host side | `hubble-ui` | other (8081 through the `make hubble-ui` port-forward; kubelet probes on `/healthz` and `/`) | open | BE-01 and FE-01 through the port-forward; the kubelet probes are out of harness scope — pod conditions read with kubectl; delivery Verification step 5 covers them |

### FE-01: Hubble UI receives Relay status and `kube-system` flows through `hubble-relay-ui-ingress`
- **Area:** Hubble UI namespace view (top-bar connection indicator and flows table). Its data comes from the UI backend's connection to Hubble Relay, which the policy admits (platform/cilium/hubble-networkpolicy.yaml:16-23). The kind cluster has three nodes (platform/kind/cluster.yaml:9, 25, 27).
- **Target:** hubble_ui
- **Writes:** no
- **Preconditions:** None. The UI has no login, and no test data is needed. While the page is open, the UI backend keeps its own connection to Relay (`FLOWS_API_ADDR=hubble-relay:80` in Cilium 1.20.3 chart member `cilium/templates/hubble-ui/deployment.yaml`, lines 127-128, outside this working tree), and Hubble records that connection as `hubble-ui` → `hubble-relay` flows while it is active (`monitorAggregation: medium` and `monitorInterval: "5s"` in chart member `cilium/values.yaml`, lines 678-681, also outside this working tree).
- **Steps:**
  1. Open `/?namespace=kube-system` in the browser.
  2. Wait up to 30 s for the Hubble UI top bar. Its namespace selector in the top-left corner shows `kube-system`.
  3. Wait up to 60 s for the flows table below the service map to fill and for the connection indicator at the right end of the top bar to show a flow rate and a node count.
  4. In the flows table, find a row whose `Source Identity` is `hubble-ui` and whose `Destination Identity` is `hubble-relay`, each with the subtitle `kube-system`. If none is listed yet, keep the page open for up to 60 s more.
- **Expected:** The connection indicator shows a flow rate in `flows/s` and the node count `3/3 nodes`, so the UI backend received Relay's `ServerStatus` and `GetNodes` answers and Relay reports all three nodes as connected (platform/cilium/hubble-networkpolicy.yaml:16-23) (unverified — confirm at run time) (exact text — brittle). The flows table lists at least one row with `Source Identity` `hubble-ui`, `Destination Identity` `hubble-relay`, `Destination Port` `4245` and `Verdict` `forwarded`, the pod-to-pod path into `hubble-relay` that the policy admits (platform/cilium/hubble-networkpolicy.yaml:17-23) (unverified — confirm at run time)
- **Edge cases:**
  - With `kube-system` selected, choose `Dropped` in the verdict filter in the top bar: no listed row has `Source Identity` `hubble-ui` and `Destination Identity` `hubble-relay`, although rows from other sources may be listed. Choose `Any verdict` afterwards (platform/cilium/hubble-networkpolicy.yaml:17-23) (unverified — confirm at run time)
  - Note the time and reload the page; if the reloaded page shows no namespace, choose `kube-system` in the namespace selector. Within 60 s the connection indicator again shows `3/3 nodes`, and the flows table lists a `hubble-ui` → `hubble-relay` row on port `4245` with verdict `forwarded` whose `Timestamp` is later than the reload (platform/cilium/hubble-networkpolicy.yaml:17-23) (unverified — confirm at run time)

## BE Test Scenarios

### BE-01: The Hubble UI pod selected by `hubble-relay-ui-ingress` still answers through the host port-forward
- **Area:** hubble-ui frontend nginx (port 8081) and its backend proxy in the pod the policy selects (platform/cilium/hubble-networkpolicy.yaml:10-15). The pod is reached through `make hubble-ui` (Makefile:41-43) on Service `hubble-ui`, port 80 → 8081 (Cilium 1.20.3 chart member `cilium/templates/hubble-ui/service.yaml`, lines 33-36, outside this working tree). The contract keeps this host access open (docs/architektura.md:76; docs/plans/2026-10-21-t03-sec-fixes.md:152).
- **Target:** hubble_ui
- **Writes:** no
- **Preconditions:** None. Requests are anonymous and carry no Authorization header, because the nginx server block has no auth directives (Cilium 1.20.3 chart member `cilium/templates/hubble-ui/_nginx.tpl`, lines 2-49, outside this working tree).
- **Method:** GET /
- **Headers:** none
- **Payload:** none
- **Expected:** 200 with a `Content-Type` header that starts with `text/html`. qa-redact withholds the non-JSON HTML body, so record its withheld byte count. nginx in the selected pod serves the Hubble UI `index.html` through `try_files` in the Cilium 1.20.3 chart's `templates/hubble-ui/_nginx.tpl`, a template outside this working tree (unverified — confirm at run time)
- **Edge cases:**
  - GET `/healthz`: 200 with `Content-Length: 2` and a 2-byte withheld body. It comes from `return 200 'ok'` in the chart template's `location /healthz`, the path that kubelet's liveness probe calls from the host (unverified — confirm at run time)
  - GET `/api/`: the status is neither 502 nor 504, because nginx proxies `/api` to the hubble-ui backend on port 8090 over loopback inside the same pod, and the backend answers. The exact status is not pinned (unverified — confirm at run time)

## Out of harness scope
- Paths from inside a `hubble-ui` pod, state rows 2-4: a connection into `hubble-relay` on a port other than 4245, such as probe port 4222, or into another `hubble-ui` pod on 8081 or 8090 is dropped (`Policy denied`), and a connection into another `hubble-ui` pod on TCP 4245 is admitted and then refused, which is BLK-01 (platform/cilium/hubble-networkpolicy.yaml:10-23). No delivery Verification step covers these rows — the client must run inside a `hubble-ui` pod in `kube-system`, which browser/HTTP/DB cannot do.
- Deny paths from pods outside `hubble-ui`, state rows 5-8 (platform/cilium/hubble-networkpolicy.yaml:10-23): delivery Verification step 8 checks rows 5 and 8 from a pod in `default`, where curl to the `hubble-relay` and `hubble-ui` Services in `kube-system` times out (exit 28) and Hubble records `DROPPED` (`Policy denied`) to `hubble-relay` port 4245 and `hubble-ui` port 8081 (docs/plans/2026-10-21-t03-sec-fixes.md:141-151). No delivery step targets rows 6 and 7 — the client must be a pod inside the cluster, which browser/HTTP/DB cannot start.
- Residual risk in docs/architektura.md:76: the same probe pod reaches the Kubernetes API and the agent metrics on the worker node IP, port 9965 (exit 0) (docs/plans/2026-10-21-t03-sec-fixes.md:151) — this needs an in-cluster pod, and port 9965 on a node IP is not a configured target.
- `make cluster` applies `hubble-relay-ui-ingress` after the Cilium release and before `cilium status` (Makefile:32-37), prints `created`, `configured` or `unchanged` for it and exits 0. A rerun prints `Klaster secure-k8s-aiops już istnieje.` and `unchanged` without recreating any kube-system pod, and `kubectl apply --dry-run=server` accepts the manifest (docs/plans/2026-10-21-t03-sec-fixes.md:73, 133-134) — these are make and kubectl CLI runs.
- Kubelet probes keep `hubble-relay` and `hubble-ui` Ready after `rollout restart`, state rows 10 and 12 (docs/plans/2026-10-21-t03-sec-fixes.md:136) — these are pod conditions read with kubectl.
- Through `make hubble-relay`, `hubble observe --from-label k8s-app=hubble-ui --to-label k8s-app=hubble-relay` lists at least one `FORWARDED` flow on `:4245` and no `DROPPED`, state row 9 (docs/plans/2026-10-21-t03-sec-fixes.md:140) — this is hubble CLI over gRPC on localhost:4245, not a configured target; FE-01 checks the same flows in the UI.
- SEC-002 success path: `make -n cluster` renders the prometheus-operator-crds chart reference with `@sha256:6a5f0e0d…` and `--version 32.0.1`, and the Cilium chart reference with `@sha256:e84f73cc…` and `--version 1.20.3`. After `make cluster`, `helm list` shows `cilium-1.20.3` and `prometheus-operator-crds-32.0.1` as `deployed` (Makefile:29-35; platform/versions.env:4-7; docs/plans/2026-10-21-t03-sec-fixes.md:105, 133) — these are make and helm CLI runs.
- SEC-002 error path: `make cluster CILIUM_CHART_DIGEST=sha256:6a5f0e0d7e53f0c9336d6ff56fbf4ff506a1a0d8251a26567b11cbbdef2c01b2` exits non-zero with `chart reference digest mismatch`, and `helm history cilium --max 1` shows the same REVISION as before the attempt (docs/plans/2026-10-21-t03-sec-fixes.md:11, 135) — this is a make/helm failure with no browser or HTTP surface.
- `cilium status --wait` reports OK for Cilium, Operator, Envoy DaemonSet and Hubble Relay, and the full `cilium connectivity test` passes with the policy applied (Makefile:37; docs/plans/2026-10-21-t03-sec-fixes.md:137, 153) — this is cilium CLI output, not served on a target.
- The documentation agrees with the delivered files: the chart pinning rule (docs/architektura.md:23), the vendor-image risk paragraph between the Kubernetes 1.36 paragraph and `## Namespace'y i Pod Security` (docs/architektura.md:25-29), and the policy paragraph (docs/architektura.md:76) (docs/plans/2026-10-21-t03-sec-fixes.md:119) — this is static text with no runtime behaviour.
