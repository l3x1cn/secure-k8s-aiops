# Code review: delivery/t03-kind-cilium-hubble (a5128d4..HEAD)

Delivered from `docs/plans/2026-10-21-t03-sec-fixes.md` (SEC-001..003 of `docs/reviews/2026-10-21-delivery-t03-kind-cilium-hubble.md`). Reviewed: `platform/cilium/hubble-networkpolicy.yaml`, `Makefile`, `platform/versions.env`, `docs/architektura.md`, `docs/testing/plans/2026-10-21-t03-sec-fixes-test-plan.md`.

No CRITICAL, HIGH or MEDIUM findings. The earlier SEC-001, SEC-002 and SEC-003 are closed. IDs below number this report only.

### [LOW] SEC-001: `hubble-relay-ui-ingress` lets hubble-ui pods reach hubble-ui pods on TCP 4245, contradicting "do UI nic"

**ID:** SEC-001
**Location:** `platform/cilium/hubble-networkpolicy.yaml:10-23`
**Category:** Security
**CWE:** CWE-284
**Effort:** easy

**Problem:**
The policy selects both `hubble-relay` and `hubble-ui` pods (lines 10-14), and its one ingress rule (lines 16-23) applies to both. So `k8s-app=hubble-ui` pods are also admitted into `hubble-ui` pods on TCP 4245. The file comment (line 2, "do UI nic"), `docs/architektura.md:76` ("do Hubble UI nie dopuszcza ruchu z podów") and the SEC-001 remediation in the earlier review all say no pod reaches the UI. The QA plan recorded the same thing as BLK-01. This merges the security finding, MAINT-004 of the quality auditor and DOC-001 of the documentation auditor (same cause; the documentation auditor marked it needs-decision).

**Impact:**
None exploitable today: the UI listens only on 8081 and 8090, and there is one replica. The contract that T07 and T12 will quote is looser than the text claims. A future Relay-client rule added to this policy would also open the same port on the UI.

**Remediation:**
Either split the policy in two, or reword the file comment and `docs/architektura.md:76` to match what the policy enforces.

```yaml
# policy 1: podSelector k8s-app=hubble-relay, ingress from k8s-app=hubble-ui on TCP 4245
# policy 2: hubble-ui-deny-ingress, podSelector k8s-app=hubble-ui, policyTypes: [Ingress], no rules
```

If split: update `docs/architektura.md:76` and the QA plan, rerun the server dry-run and the plan's Verification steps 5, 7 and 8.

---

### [LOW] SEC-002: the residual-risk paragraph omits `cilium-envoy` metrics on port 9964

**ID:** SEC-002
**Location:** `docs/architektura.md:76`
**Category:** Security
**CWE:** CWE-200
**Effort:** trivial

**Problem:**
The paragraph lists ports 9962, 9963 and 9965 as readable from any pod and names only the agent and operator as host-network components. The `cilium-envoy` DaemonSet also runs in the host network and serves metrics on 9964 (chart default `envoy.prometheus.enabled: true`, not changed by `platform/cilium/values.yaml`). The planned #7 replacement line in the delivery plan copies the same three ports.

**Impact:**
Any pod can read Envoy metrics (listeners, upstream clusters, traffic volume). The exposure is small, but it is missing from the accepted-risk record that T07 will inherit.

**Remediation:**
Add Envoy and 9964 to line 76 and to the #7 replacement line before publishing it.

```markdown
Agent, operator i Envoy Cilium (DaemonSet `cilium-envoy`) działają w sieci hosta, więc NetworkPolicy ich nie obejmuje: metryki na portach 9962, 9963, 9964 i 9965 są czytelne z każdego poda (ryzyko szczątkowe, T07).
```

---

### [LOW] MAINT-001: the pinning rule is not carried into the T04 description (#4)

**ID:** MAINT-001
**Location:** `docs/architektura.md:23`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
Issue #4 still says `helm upgrade --install --wait --version <z versions.env>`. `docs/architektura.md:3` requires a contract change to update the descriptions of the tasks it affects, and the delivery plan edits only #7.

**Impact:**
Someone implementing #4 as written could reintroduce the version-only install that SEC-002 of the earlier review closed.

**Remediation:**
Add a `gh issue edit 4` step next to the #7 edit: `helm upgrade --install --wait <chart>@<*_CHART_DIGEST> --version <*_VERSION>` (both from `platform/versions.env`).

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 3 |
| False positives removed | 0 |
| Severity adjustments | 0 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)
- The shared `podSelector` in one NetworkPolicy is the design cause of SEC-001, and `architektura.md:76` ("Nowy klient Hubble Relay wymaga reguły w tej polityce") would repeat it for each new client.
- SEC-002 and MAINT-001 are both incomplete post-delivery issue edits (#7 port list, #4 Helm rule).

### Challenged Findings
- None removed or downgraded. The challenger confirmed all findings and reinstated none of the 13 security rejections. It could not check the quality and documentation rejections, which arrived elided. It noted that the "Relay plaintext gRPC" rejection reason ("older config") is wrong, although the rejection stands (the SEC-001 decision leaves Relay without authentication and uses the NetworkPolicy as the control).

### Rejected by auditors (self-falsification)
- Trivy KSV-0037, NetworkPolicy in kube-system — a NetworkPolicy must live in the namespace of the pods it selects.
- Pods in other namespaces faking the `k8s-app=hubble-ui` label — a podSelector without a namespaceSelector matches only kube-system.
- Bypass through agent Hubble port 4244 — client certificate required.
- Chart digest does not pin images — all Cilium images run by `@sha256`.
- Helm ignores `@digest` with `--version` — mismatch error observed.
- Stale or wrong chart digests — both digests resolve to the expected charts.
- SEC-003 accepted although a fix exists — Cilium v1.20.3 and kind v0.33.0 are the newest releases.
- NetworkPolicy placed in `platform/` instead of `deploy/base/` — recorded plan decision.
- Digest with `--version` might not validate; digest instruction in `versions.env` — verified with `helm pull`.

### Doctrine-gap candidates
- No NetworkPolicy convention of one policy per protected workload.
- Raw manifests outside `deploy/` are not validated or scanned in CI (T06, T15 cover `deploy/` only).
- Controls in kube-system have no automated regression test (T12 covers app namespaces).
- The chart-pinning rule covers only OCI registries (T17 charts come from classic Helm repositories).
- No provenance check (signature) when a pin is bumped.
- No rule for deriving the residual host-network exposure list from actual node listeners.
