Review scope: changes since 0b29104 (11 files)

# Code review: t04-powtarzalne-wdrozenie (0b29104..HEAD)

Delivered from `docs/plans/2026-11-05-t04-powtarzalne-wdrozenie.md`. Reviewed: `Makefile`, `platform/versions.env`, `platform/kind/cluster.yaml`, `deploy/base/{kustomization,namespaces}.yaml`, `deploy/overlays/local/kustomization.yaml`, `scripts/{secrets,doctor}.sh`, `README.md`, `docs/architektura.md`.

No CRITICAL, HIGH or MEDIUM findings. The documentation auditor found no drift. MAINT-001 and DOC-001 of the first T03 review and MAINT-001 of the second T03 review are closed by this change. Live checks already done: two from-scratch `make up` runs, an idempotent third run, secrets, overlay, port-forward (plan Verification, all passed).

### [LOW] SEC-001: Existing `fault-token` value is copied into the generated YAML manifest without encoding or validation

**ID:** SEC-001
**Location:** `scripts/secrets.sh:26`
**Category:** Security
**OWASP:** A05:2025
**CWE:** CWE-74
**Effort:** easy

**Problem:**
`ensure_token_secret` reuses the value of an existing `fault-token` (`read_token` decodes `.data.token` with `base64decode`, line 21) when the copy in the other namespace is missing. `create_token_secret` writes that value unescaped into a YAML double-quoted scalar (`token: "%s"`, line 26) and pipes the manifest to `kubectl create -f -`, which accepts several YAML documents. Only values the script generates itself (64 hex characters) are safe. A value with `"`, a newline or `---` can add more documents or be altered on the way (backslash escapes are decoded, trailing newlines are dropped), so the copies end up with different values, which breaks "ta sama wartość w shop i loadgen" (`docs/architektura.md`, "Sekrety"). Only `fault-token` is affected: `orders-api-token` lives in one namespace.

**Impact:**
Today only cluster-admin can write Secrets in `shop` or `loadgen` (no Role, ClusterRole or ServiceAccount in `deploy/` or `platform/`), so no privilege boundary is crossed; a hand-edited value gives a corrupted copy and fault-runner gets 403 or `make secrets` fails. Once RBAC arrives (T11), a principal that can write Secrets in `shop` could plant a value that creates extra objects with the operator's kubeconfig on the next `make up`.

**Remediation:**
Copy the raw base64 from `.data.token` into `data:` instead of decoding it (the base64 alphabet cannot break YAML), or stop with an error when an existing value is not 64 hex characters.

```bash
# After (stop on a value the script did not generate)
case $value in
  *[!0-9a-f]*) echo "Secret $name: wartość nie pochodzi z openssl rand -hex 32; usuń sekret i uruchom make secrets." >&2; exit 1 ;;
esac
[ "${#value}" -eq 64 ] || { echo "Secret $name: wartość nie pochodzi z openssl rand -hex 32; usuń sekret i uruchom make secrets." >&2; exit 1; }
```

---

### [LOW] MAINT-001: Changing `KIND_NODE_IMAGE` has no effect on an existing cluster, and nothing says so

**ID:** MAINT-001
**Location:** `platform/versions.env:4-5`, `Makefile:38-48`
**Category:** Maintainability
**Effort:** trivial (comment) or easy (guard)

**Problem:**
`versions.env` is "jedno źródło" and `Makefile:39` says `helm upgrade --install` brings CRD and Cilium to the pins on every run. But `Makefile:44-45` skips `kind create` when the cluster exists and nothing compares the running node image with `KIND_NODE_IMAGE`. Neither `versions.env`, the `Makefile` comment nor `README.md` says a node-image change needs `make down && make up`. `docs/architektura.md:25,27` plan exactly this kind of bump (Kubernetes 1.37, a newer `kindest/node` 1.36). The behaviour existed in T03; T04 moved the image next to pins that do converge on every run.

**Impact:**
After a bump, `make up` on an existing cluster prints `Klaster secure-k8s-aiops już istnieje.` and exits 0 while the nodes keep the old version; a new Cilium on old nodes is a combination nobody tested.

**Remediation:**
Note it in `platform/versions.env`, or add a guard in the existing-cluster branch.

```make
# platform/versions.env:4
# Obraz węzłów kind (make cluster, flaga --image; działa tylko przy tworzeniu klastra: po zmianie make down && make up): ...

# optional guard (Makefile:44-45)
	@if kind get clusters | grep -qx '$(CLUSTER_NAME)'; then \
		echo "Klaster $(CLUSTER_NAME) już istnieje."; \
		img=$$(docker inspect -f '{{.Config.Image}}' '$(CLUSTER_NAME)-control-plane'); \
		[ "$$img" = '$(KIND_NODE_IMAGE)' ] || { echo "Węzły mają $$img, a KIND_NODE_IMAGE to $(KIND_NODE_IMAGE): make down && make up." >&2; exit 1; }; \
	else \
```

---

### [LOW] MAINT-002: `make up` reloads the new `:dev` image without restarting pods, while the docs say a re-run changes nothing

**ID:** MAINT-002
**Location:** `README.md:42,53`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
`make up` always runs `make images` (`Makefile:29`), which rebuilds the mutable `:dev` tag and runs `kind load` (`Makefile:72-75`). The pod template does not change (`newTag: dev`), so there is no rollout. `README.md:42` and the `Makefile:24` comment say a re-run changes nothing; `README.md:53` gives `rollout restart` only for `make images`. With `imagePullPolicy: IfNotPresent`, a container that restarts inside an existing pod (for example S5 `crash`, or a failed liveness probe) starts the new build while other pods still run the old one.

**Impact:**
A fault scenario can switch code versions mid-run with no rollout event, and a developer who runs `make up` to deploy a change keeps seeing the old code until a restart. [INFERENCE: the in-place restart behaviour was not checked live.]

**Remediation:**
Docs only; the `:dev` tag, `IfNotPresent` and the idempotency criterion stay as issue #4 requires.

```markdown
Tag `:dev` się nie zmienia: `make images` (także w `make up`) ładuje nowy obraz do węzłów bez restartu podów, a restart kontenera (np. scenariusz S5) uruchomi już nowy kod. Po zmianie kodu usługi: `make images`, potem `kubectl -n <namespace> rollout restart deployment/<nazwa>`.
```

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
- No composite: the three findings sit in different code paths and need different fixes (`scripts/secrets.sh`, the `cluster` target and `versions.env`, `README.md`).
- Coverage gap noted by the Cross-Verifier (not a finding): `ensure_token_secret` checks only that a Secret with the right name exists, not its `token` key or that the `fault-token` copies match. A hand-made `shop/fault-token` without the key, or two copies with different values, both print "już istnieje" and exit 0, and the failure shows up later as a `rollout status` timeout or 403 from `/faults/*`. The remediation of SEC-001 can also cover this.

### Challenged Findings
- No CRITICAL or HIGH findings to challenge. The Challenger confirmed all three LOW findings and their severity. It could not reject MAINT-002, because `README.md:53` describes the workflow for `make images`, not for `make up`.

### Rejected by auditors (self-falsification)
- KSV-0125 images from an untrusted registry — the registry is the project's own `ghcr.io/l3x1cn/secure-k8s-aiops`.
- `FAULTS_ENABLED=true` with an optional token lets `/faults/*` run without a token — fails closed in `services/orders/src/orders/app.py:39-40`.
- NodePort 30080 reachable on the Docker bridge — frontend is public by contract and the host mapping listens on 127.0.0.1.
- `imagePullPolicy: IfNotPresent` on `:dev` may pull from a registry — required by issue #4.
- Secret values exposed via process arguments, disk, last-applied annotation or the screen — disproved by reading `scripts/secrets.sh`.
- Race between get and create in `ensure_token_secret` — `kubectl create` fails with AlreadyExists and `set -e` stops the script.
- Deploy pipeline without pipefail could apply partial output — `kustomize build` writes nothing on error and `kubectl apply -f -` on empty input exits 1.
- Docker group is root-equivalent; Secrets unencrypted in kind's etcd; shellcheck SC1111/SC2016 in `doctor.sh:80,84` — not introduced by this diff.
- PSA namespaces lack an `enforce-version` pin; `APP_NAMESPACES` duplicates the namespace list; JSON6902 patch reaches only `containers/0`; Helm adds a release revision on every `make up`; `secrets.sh` reports "już istnieje" for a Secret without the `token` key; `kubectl apply` without `--prune`; mode 100755 of `secrets.sh`; repeated `--context`; mixed quoting; no automated tests for the scripts; namespaces lack `app.kubernetes.io` labels; yamllint line length; plain `docker build` in the README "Awarie" block; README status line "planowanie" — owner decisions recorded in the plan, existing behaviour, or outside the changed lines.
- README says "ok. 3 min" while the verification runs took 89 s and 94 s — one measurement rounded up to whole minutes, as the plan prescribes; the verification times are in the PR evidence.
- `docs/architektura.md:40` says `make up` applies the namespaces "przed sekretami i chartami" — "charty" means the platform charts in the table's namespaces; Cilium and prometheus-operator-crds install into kube-system, which `namespaces.yaml` leaves out on purpose.

### Doctrine-gap candidates
- No rule for building Kubernetes manifests from values in scripts; `scripts/secrets.sh` builds YAML with `printf` and T14 extends the same script.
- No shell linter in the pinned toolchain (`mise.toml`); a candidate for T06 (CI).
- No rule separating pins applied only at cluster creation (`KIND_NODE_IMAGE`) from pins applied on every `make up` (charts). Linked to MAINT-001.
- No rule for recording which build a fault or experiment run used while dev images use a mutable tag. Linked to MAINT-002.

### Out of scope (scope check)
None
