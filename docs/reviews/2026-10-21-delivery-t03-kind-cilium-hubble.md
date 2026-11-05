# Code Review: delivery/t03-kind-cilium-hubble

**Scope:** `40e7cdd43e43d6a6f173b6b425c6b34ce259605e..HEAD` (4 commits, 11 files), delivered from `docs/plans/2026-10-20-t03-kind-cilium-hubble.md`.
**Result:** 0 CRITICAL, 0 HIGH, 2 MEDIUM, 5 LOW. No secrets found (gitleaks, 4 commits).

Infra/config and docs change only: no application code. Delivered `Makefile`, `platform/*` and docs match the plan's literal blocks. Verified live: `make cluster` exit 0 in 1m27s, idempotent re-run, `cilium status` all OK, `cilium connectivity test` 82 tests successful with 0 failures, metrics contract (3 ServiceMonitors, 6 `hubble-metrics` entries, `POLICY_DENIED` series with workload labels), Hubble UI HTTP 200.

Performance: nothing to report (no queries, loops or unbounded fetches in the diff). Architecture: the `platform/` (T03) vs `deploy/` (T04+) split follows `docs/architektura.md:149-154`.

---

### [MEDIUM] SEC-001: Hubble Relay and Hubble UI are reachable from any pod without authentication

**ID:** SEC-001
**Location:** `platform/cilium/values.yaml:19-22`
**Category:** Security
**OWASP:** A01:2025
**CWE:** CWE-306
**Effort:** medium

**Problem:**
`hubble.relay` and `hubble.ui` are enabled. With chart defaults Relay serves plaintext gRPC (`disable-server-tls: true`, `:4245`) behind ClusterIP Service `hubble-relay:80`; the UI backend proxies flow queries to it behind `hubble-ui:80`. Neither requires authentication. The cluster has no NetworkPolicy in any namespace, and the contract applies default-deny only to `shop`, `loadgen` and `aiops` (`docs/architektura.md:53`; kube-system "bez zmian", `:36`, covers Pod Security only).

**Impact:**
A compromised pod (the planned `intruder` namespace has no egress default-deny) can run `hubble observe --server hubble-relay.kube-system.svc:80` and receive every flow: pod names, labels, IPs, ports, verdicts and drop reasons. It maps the topology and NetworkPolicy rules and watches in real time whether its probes produce `POLICY_DENIED` drops, which is the signal behind `PolicyDeniedConnections`.

**Remediation:**
Allow ingress to `hubble-relay` only from `hubble-ui`, and none to `hubble-ui` (access stays through `make hubble-ui` and `hubble observe --port-forward`). Use `networking.k8s.io/v1` as the contract requires (`docs/architektura.md:72`); decide placement first: the layout gives NetworkPolicy to `deploy/base/` (T04, T11-T13), T03 files live in `platform/`. After applying, re-run plan Verification steps 6-8. Alternatively record the exposure as residual risk in the T07 threat model.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hubble-relay-ui-ingress
  namespace: kube-system
spec:
  podSelector:
    matchExpressions:
      - {key: k8s-app, operator: In, values: [hubble-relay, hubble-ui]}
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              k8s-app: hubble-ui
      ports:
        - protocol: TCP
          port: 4245
```

---

### [MEDIUM] SEC-002: Helm charts are installed by mutable OCI version tag without digest

**ID:** SEC-002
**Location:** `Makefile:28-34`
**Category:** Security
**OWASP:** A08:2025
**CWE:** CWE-494
**Effort:** easy

**Problem:**
`prometheus-operator-crds` and `cilium` are installed with `--version` only (`platform/versions.env:3-4`). OCI tags can be re-pushed. Every other external artifact of this change is pinned by digest (`platform/kind/cluster.yaml:10,26,28`; `docs/architektura.md:15,19`). The contract records a compromised upstream release as a real threat (`docs/architektura.md:23`).

**Impact:**
A replaced `1.20.3` or `32.0.1` chart controls a privileged DaemonSet on privileged kind node containers; the next `make cluster` on any machine or CI installs it.

**Remediation:**
Record chart digests next to the versions in `platform/versions.env` and install by `tag@digest`; state the chart pinning rule in `docs/architektura.md:11,23` (contract change goes through a PR, `docs/architektura.md:3`). Land together with MAINT-001 as one change to the pin schema.

```make
# platform/versions.env
CILIUM_CHART_DIGEST=sha256:e84f73cc9edcb0d00306ecee57a56f20bb32dddad77c8cef3af62d844ec8adea
PROMETHEUS_OPERATOR_CRDS_CHART_DIGEST=sha256:6a5f0e0d7e53f0c9336d6ff56fbf4ff506a1a0d8251a26567b11cbbdef2c01b2

# Makefile
helm upgrade --install cilium $(CILIUM_CHART):$(CILIUM_VERSION)@$(CILIUM_CHART_DIGEST) \
	--kube-context $(KUBE_CONTEXT) --namespace kube-system \
	--values platform/cilium/values.yaml --wait --timeout 10m
```

Digests were observed by the auditor with `helm pull`; re-check them before pinning.

---

### [LOW] SEC-003: Pinned third-party images carry HIGH/CRITICAL CVEs with no newer upstream fix

**ID:** SEC-003
**Location:** `platform/versions.env:3`
**Category:** Security
**OWASP:** A03:2025
**CWE:** CWE-1395
**Effort:** easy

**Problem:**
Trivy (HIGH and CRITICAL) on the rendered images: `cilium-envoy` 1 CRITICAL (CVE-2025-68121) and 24 HIGH, `cilium` 3 HIGH, `hubble-ui` 1 HIGH, `hubble-ui-backend` 4 HIGH, `kindest/node:v1.36.4` 4 CRITICAL and 229 HIGH. Cilium 1.20.3, `prometheus-operator-crds` 32.0.1 and `kindest/node:v1.36.4` are the newest releases published.

**Impact:**
Mostly theoretical in a loopback-only kind cluster; the largest exposure is the Go `net/http` DoS class in the `hubble-ui` backend, which any pod can reach (SEC-001).

**Remediation:**
Record it as accepted vendor-image risk in the T07 threat model. Scope the T06 Trivy gate to project images or use a `.trivyignore` with expiry dates for vendor images. Move the pins when Cilium 1.20.4 or a newer `kindest/node` 1.36 image ships.

---

### [LOW] MAINT-001: kind node image digest is repeated three times outside the declared single source

**ID:** MAINT-001
**Location:** `platform/kind/cluster.yaml:10-28`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
`kindest/node:v1.36.4@sha256:099e...faed` appears at `cluster.yaml:10,26,28` and at `docs/architektura.md:9`, while `platform/versions.env:1` calls itself the single source for external images.

**Impact:**
The planned move to Kubernetes 1.37 (`docs/architektura.md:25`) needs four synchronized edits; a missed line gives nodes of different Kubernetes versions.

**Remediation:**
Add `KIND_NODE_IMAGE` to `platform/versions.env`, pass `--image '$(KIND_NODE_IMAGE)'` at `Makefile:26`, delete the three `image:` lines, and extend the sync note at `versions.env:2` to cover `docs/architektura.md:9`. Smaller alternative: a YAML anchor on line 10, aliases on lines 26 and 28.

---

### [LOW] MAINT-002: `.av/local.toml` sits under the versions.env exception comment in `.gitignore`

**ID:** MAINT-002
**Location:** `.gitignore:14`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
The QA configuration commit appended `.av/local.toml` after `# Wyjatek: wersje chartow i obrazow (T04)...` and `!platform/versions.env`, so it reads as part of that exception.

**Impact:**
Cosmetic; the entry works (the file is ignored).

**Remediation:**
Move the line into the "Sekrety i dostep do klastra" group, above the exception comment.

```diff
 *.env
 kubeconfig*
+.av/local.toml
 # Wyjatek: wersje chartow i obrazow (T04) sa czescia repozytorium
 !platform/versions.env
-.av/local.toml
```

---

### [LOW] MAINT-003: QA report named in a commit subject is git-ignored by the unanchored `reports/` pattern

**ID:** MAINT-003
**Location:** `.gitignore:7`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
`.gitignore:7` (`reports/`) is meant for the top-level `reports/` directory (`docs/architektura.md:163`) but also matches `docs/testing/reports/`, the location the QA plugin requires. Commit `47b127b` is titled "add QA plan and report", yet only the plan was committed. The report (QA-001, LOW, FE-01 edge 2) and the loop-state JSON exist on disk only.

**Impact:**
The QA result of this delivery is not in the repository history.

**Remediation:**
Either anchor the pattern (`/reports/`) and commit the report, or keep reports out of git and correct the commit subject convention. Decision for the owner.

---

### [LOW] DOC-001: Repository-structure line for `Makefile` omits the T03 `cluster` target

**ID:** DOC-001
**Location:** `docs/architektura.md:147`
**Category:** Documentation
**Drift-class:** decision
**Fix-policy:** needs-decision
**Effort:** trivial

**Problem:**
The tree reads `# doctor (T02); up, down, images, secrets, test, report (T04 i dalej)`, but `Makefile:13` now declares `doctor cluster hubble-ui`. Line 149 (`platform/`) already credits T03, so the section disagrees with itself. Merged with the quality finding on the same line.

**Impact:**
Low: `make cluster` is documented in `README.md:33-40` and `docs/architektura.md:40`, `make hubble-ui` in `:49`. Only the repository map is incomplete.

**Remediation:**
Add `cluster (T03)` following the line's pattern. Whether to add `hubble-ui` is an owner decision (the line lists no other port-forward helpers).

```diff
-├── Makefile               # doctor (T02); up, down, images, secrets, test, report (T04 i dalej)
+├── Makefile               # doctor (T02); cluster (T03); up, down, images, secrets, test, report (T04 i dalej)
```

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 7 |
| False positives removed | 0 |
| Severity adjustments | 1 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)
- SEC-002 and MAINT-001 share a cause (the single-source pin schema in `platform/versions.env` is incomplete) but not an edit set; each closes on its own, so no composite. Land them as one pin-schema change to avoid two pinning conventions.
- The quality finding on `docs/architektura.md:147` and DOC-001 are the same defect; reported once as DOC-001.
- Coverage gap: the placement of the SEC-001 fix (`platform/` vs `deploy/base/`, create-only branch vs every `make cluster` run) was not decided by any auditor.

### Challenged Findings
- DOC-001 downgraded MEDIUM to LOW: the contract-relevant facts are already documented; only the repository map is stale.
- Reinstated at LOW as MAINT-003: "commit 47b127b announces a QA report that is not in the tree", wrongly rejected as "by design" (the cited rule targets top-level `reports/`).
- All other findings confirmed; the remaining spot-checked rejections were sound.

### Rejected by auditors (self-falsification)
- Command injection via `versions.env` values in Makefile recipes: no trust boundary, anyone who can edit `versions.env` can edit the Makefile.
- Hubble UI port-forward exposed beyond localhost: checked live, listens on 127.0.0.1 and ::1 only.
- NodePort host mappings reachable from the LAN: checked live, all bound to 127.0.0.1.
- Trivy KSV hardening results for hubble-ui and hubble-relay: kube-system deliberately left without Pod Security hardening (`docs/architektura.md:36`).
- `hubble-relay-config` ConfigMap "stores secrets": false positive, only file paths.
- Unbounded Hubble metric cardinality: runtime-only, belongs to T16 capacity checks.
- `kind get clusters | grep -qx` hides errors: falls through to `kind create cluster`, which fails loudly.
- Node image not the latest patch: no `kindest/node:v1.36.5` is published.
- Hubble CA key stored in the Helm release Secret: no extra exposure (`tls.auto.method: helm` default).
- Cilium version duplicated in `versions.env` and `docs/architektura.md`: deliberate, recorded sync note.
- Line-number citations in QA config comments: required by the qa:env-config evidence rule; all verified.
- `cluster` target bundles create, CRDs, Cilium and verify: 15-line recipe, issue #3 requires one idempotent target.
- Existing cluster not reconciled on config drift: deliberate (`Makefile:19`).
- `labelsContext` repeated six times: Cilium syntax requires it.
- Quoting inconsistency of `CLUSTER_NAME` vs `KUBE_CONTEXT`: constants, plan-prescribed.
- No cluster-delete target, README hardcodes the name: deferred to T04 `down`.
- Port mappings for services not yet deployed: contract `docs/architektura.md:42-48`.
- CRD release lacks `helm.sh/resource-policy: keep`: no target uninstalls the release.
- Envoy metrics have no ServiceMonitor: contract limits ServiceMonitors to agent, operator, hubble.
- Helm 4 `--wait` and CRD Established: runtime behavior, covered by plan Verification step 2 (passed).
- `make up` described as creating the cluster in `docs/karta-projektu.md:30`: T04 scope, not stale.
- No YAML/Makefile/Markdown linters configured: deferred to T06.
- README status "planowanie"; `prometheus-operator-crds` namespace "—"; `.gitignore` exception comment crediting T04: pre-existing or accurate, not part of this diff.

### Doctrine-gap candidates
- No single-source rule for pinned digests: every pinned version or digest should have exactly one config home (`mise.toml` or `platform/versions.env`), doc copies carrying a sync note (linked to SEC-002, MAINT-001).
- Chart pinning rule missing from the version contract: images are pinned by digest, charts only by version (linked to SEC-002).
- Threat model and network-flow contract do not cover the kube-system observability plane: default-deny covers `shop`, `loadgen`, `aiops`; the T07 residual-risk list omits unauthenticated Hubble Relay, UI and metrics (linked to SEC-001).
- No policy separating vendor-image CVEs from project-image CVEs in the Trivy CI gate (linked to SEC-003).
