Review scope: changes since 6192151 (5 files)

# Code review: T10 images in CI and publication to GHCR

Branch `t10-obrazy-ghcr`, range `61921510ecd7a8bcc7e6d36bc6c67fdd6f6e291e..HEAD`, delivered from `docs/plans/2026-11-06-t10-obrazy-ghcr.md`.

## Summary

- Changed: `.github/workflows/images.yml` (new), `Makefile` (2 comment lines), `README.md`, `docs/architektura.md`, the plan file.
- No CRITICAL or HIGH findings. 1 MEDIUM documentation finding, 1 MEDIUM composite (cancelled run), 4 LOW.
- Automated scans are clean: actionlint 1.7.12 exit 0; zizmor 1.32.0 default persona "No findings"; Semgrep (7 packs, 68 rules) 0 findings; gitleaks and trufflehog 0 secrets; `trivy fs uv.lock` and `pip-audit` 0 vulnerabilities; `make lint` passes.
- Not exercised: the local `docker buildx` build (Docker daemon inactive), QA (bootstrap declined), the first CI run on GitHub.

## Findings

### [MEDIUM] COMP-001: The required `images` check is skipped, and so counts as passed, when the Images run is cancelled
**Status:** 🚫 Rejected (2026-11-06) — dissolved into components

**ID:** COMP-001
**Location:** `.github/workflows/images.yml:66`
**Category:** Composite
**Effort:** trivial
**Composed-of:** SEC-002, MAINT-001
**Origin:** review

**Problem:**
The `images` job runs only if `${{ !cancelled() && github.event_name == 'pull_request' }}`. When a run is cancelled, `images` (`needs: build`) is skipped by its own condition. GitHub reports a job skipped by a conditional as "Success", and `skipped` is a passing state for required checks. GitHub's "Troubleshooting required status checks" page recommends `always()` with `needs` for required checks that depend on other jobs. [INFERENCE: cancellation was not observed in this repository; it follows from the cited documentation.]

**Impact:**
`images` is the only merge gate T10 adds. Cancelling the run lets a PR whose images do not build pass the ruleset. Cancelling needs write access and merging still needs one approval. The `push (…)` jobs on `main` then fail and that commit gets no images. The claims "zielony tylko wtedy, gdy zbudowały się wszystkie obrazy" (`docs/architektura.md:41`, `images.yml:2-3`) are false meanwhile. T15 will add `trivy image` to `build` and rely on this aggregator, so the same cancellation would bypass that gate.

**Remediation:**

```yaml
# Before
    if: ${{ !cancelled() && github.event_name == 'pull_request' }}

# After: a cancelled run makes needs.build.result "cancelled", the test fails, the PR stays blocked
    if: ${{ always() && github.event_name == 'pull_request' }}
```

The job has one `test` step and `timeout-minutes: 5`, so `always()` cannot leave it hanging. Re-run actionlint and zizmor afterwards. To confirm on GitHub, cancel the Images run of the test PR from step 4 of "Po dostarczeniu" and check that `gh pr checks <PR> --required` shows `images fail`.

---

### [MEDIUM] DOC-001: The "four places" checklist for a new image leaves out the overlay `local` image list
**Status:** ✅ Fixed (2026-11-06)
**Verification:** advisory — grep, git diff and actionlint ran and passed; the soft check (Read docs/architektura.md:46 contains "w pięciu miejscach") rests on a model re-read of prose

**ID:** DOC-001
**Location:** `docs/architektura.md:46`
**Category:** Documentation
**Drift-class:** decision
**Fix-policy:** needs-decision
**Effort:** trivial
**Decision:** A — In docs/architektura.md replace line 46 with "- Nowy obraz (np. anomaly-detector w T24) dopisuje się w pięciu miejscach: matrixy jobów `build` i `push` w `images.yml`, cel `images` w `Makefile`, lista `images:` (`newTag: dev`) w `deploy/overlays/local/kustomization.yaml` i tabela powyżej. Ruleset się nie zmienia.", in .github/workflows/images.yml replace the comment on line 9 with "# Lista obrazów jest w matrixach jobów build i push, w celu images w Makefile i w deploy/overlays/local/kustomization.yaml (images:, newTag: dev): zmieniaj razem.", and in Makefile replace the comment on line 94 with "# Ta sama lista obrazów jest w matrixach jobów build i push w .github/workflows/images.yml i w deploy/overlays/local/kustomization.yaml (images:, newTag: dev): zmieniaj razem."; change no other line in these three files and edit neither deploy/overlays/local/kustomization.yaml nor anything under docs/plans/. [user, 2026-11-06]
**Verification-plan:** grep -c 'czterech miejscach' docs/architektura.md → 0; grep -n 'deploy/overlays/local/kustomization.yaml' docs/architektura.md .github/workflows/images.yml Makefile → exactly three matched lines, at docs/architektura.md:46, .github/workflows/images.yml:9 and Makefile:94; git diff -U0 HEAD -- Makefile → a single hunk @@ -94 +94 @@ whose one - line and one + line both begin with #; git diff -U0 HEAD -- .github/workflows/images.yml → a single hunk @@ -9 +9 @@; mise exec actionlint@1.7.12 -- actionlint → no output; Read docs/architektura.md:46 → the line contains "w pięciu miejscach" and "lista `images:` (`newTag: dev`) w `deploy/overlays/local/kustomization.yaml`" (soft)
**Decision-pin:** block=daddcf4b414730fc7c19592f9ab2b39e55cd54be39ae789371fde5d0d39a1bb9 | docs/architektura.md=ce8f9916ade073cbc16bbd761aa50a9ea2dee06c:edit | .github/workflows/images.yml=b8c82199ca684888fd61964aeb9ca65c1f7737de:edit | Makefile=1b9500254975e77c48489f386013d2883bf896e8:edit | deploy/overlays/local/kustomization.yaml=b34060e64ac7ae051760e678ecff1f7f7b70ee76:ref | docs/plans/=unpinnable:ref
**Dispatch:** attempt 1 dispatched 2026-11-06

**Problem:**
The line says a new image (e.g. anomaly-detector in T24) is added "w czterech miejscach": the `build` and `push` matrices in `images.yml`, the `images` target in `Makefile` and the table. The image list is also written out per image in the `images:` block of `deploy/overlays/local/kustomization.yaml:7-13` (`newTag: dev`). The same section says the overlay sets the tag (line 31) but the checklist skips it. Nothing checks it: `scripts/manifests.sh` only runs `kustomize build | kubeconform`. The comments `images.yml:9` and `Makefile:94` omit the overlay too. The plan posts the same four-place text to #24.

**Impact:**
Following the checklist, T24 would leave the overlay out. The Deployment would have no tag, so Kubernetes would use `:latest`. kind has only `:dev` loaded and GHCR has no `latest` by design, so the pod ends in ImagePullBackOff and `make deploy` times out. Overlay `cloud` (T29) will add another per-image list.

**Remediation:**
Either extend the sentence to every place ("w pięciu miejscach: … lista `images:` (`newTag: dev`) w `deploy/overlays/local/kustomization.yaml` …") and update the comments in `images.yml:9` and `Makefile:94`, or limit it explicitly to "budowa i publikacja" and point to the overlay for the tag. Correct the planned comment for #24 to match.

---

### [LOW] SEC-001: "Publish only from main" is not enforced at the registry; the unsigned, mutable `sha-<7>` tag is the deploy contract
**Status:** ✅ Fixed (2026-11-06)

**ID:** SEC-001
**Location:** `.github/workflows/images.yml:115`
**Category:** Security
**OWASP:** A08:2025
**CWE:** CWE-345
**Effort:** medium

**Problem:**
The `push` job publishes mutable `sha-<7>` tags with no signed provenance. Only this workflow's `on` and `if` conditions keep publication to `main`. GitHub documents that a package linked to a repository inherits its access, so any same-repo workflow that declares `packages: write`, and any write collaborator, can overwrite a tag. BuildKit `mode=max` provenance is unsigned and labels are self-declared. `docs/architektura.md:43` makes such a tag what overlay `cloud` (T29) deploys. [INFERENCE: the inheritance comes from GitHub documentation; the packages do not exist yet, so it was not exercised.]

**Impact:**
A write collaborator, or a stolen collaborator PAT, can push a backdoored image under the tag of the latest `main` commit without review. Severity was lowered from MEDIUM to LOW by the challenger: only trusted write accounts can do this, nothing in this change deploys from GHCR yet (`deploy/overlays/cloud/` holds only `.gitkeep`), and an attestation adds no enforcement unless something verifies it at admission.

**Remediation:**
Proportionate: record it as a residual risk of the supply-chain actor in the T07 threat model (#7) and, in T29, make overlay `cloud` pin `sha-…@sha256:<digest>` taken from the `main` run, so the digest goes through review (as `docs/architektura.md:23` does for vendor charts). Stronger: `actions/attest-build-provenance` v4.2.2 in the `push` job (`id-token: write`, `attestations: write`, `subject-digest` from the build-push `digest` output, `push-to-registry: true`), verified before deploy with `gh attestation verify`.

---

### [LOW] SEC-002: The required `images` check uses `!cancelled()`, so a cancelled run leaves it skipped
**Status:** ✅ Fixed (2026-11-06)

**ID:** SEC-002
**Part-of:** COMP-001
**Location:** `.github/workflows/images.yml:66`
**Category:** Security
**OWASP:** A10:2025
**CWE:** CWE-754
**Effort:** trivial

**Problem:**
Same cause as COMP-001 as seen by the security auditor: `if: ${{ !cancelled() && github.event_name == 'pull_request' }}` skips `images` after a cancel, and a skipped required check counts as passing.

**Impact:**
A PR can be merged with one approval after its Images run was cancelled before the build legs finished. A broken Dockerfile then reaches `main`.

**Remediation:**

```yaml
    if: ${{ always() && github.event_name == 'pull_request' }}
```

Add a "cancelled run → `images` fails" case to step 4 of "Po dostarczeniu".

---

### [LOW] MAINT-001: The required check `images` passes when the Images run is cancelled
**Status:** ✅ Fixed (2026-11-06)

**ID:** MAINT-001
**Part-of:** COMP-001
**Location:** `.github/workflows/images.yml:66`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
Same cause as COMP-001 as seen by the quality auditor. The plan records `!cancelled()` but gives no reason for the cancel case, so it is not a deliberate omission. Only a manual or API cancel of the run triggers it (a job timeout cancels the job, not the run, so `images` still runs and fails).

**Impact:**
The contract claim that `images` is green only when every image built does not hold for a cancelled run.

**Remediation:**

```yaml
# After
    if: ${{ always() && github.event_name == 'pull_request' }}
```

---

### [LOW] MAINT-002: The BuildKit image in the build jobs comes from a moving tag
**Status:** ✅ Fixed (2026-11-06)

**ID:** MAINT-002
**Location:** `.github/workflows/images.yml:47` and `:99`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
`docker/setup-buildx-action` v4.4.1 runs without `driver-opts`, so Buildx pulls `moby/buildkit:buildx-stable-1`. The rest of the project pins its inputs: actions by SHA, base images by digest, charts and the kind node image by digest. The Dockerfiles' `# syntax=docker/dockerfile:1` floats too, so a BuildKit pin alone is only a partial fix. The security side is covered: buildx 0.36 and later check the signatures of `moby/buildkit` tags. [INFERENCE: the runner's buildx version was not observed.]

**Impact:**
BuildKit can change with no commit in this repository, so the result of the required check is not reproducible. In `push` the same daemon publishes with a `packages: write` token.

**Remediation:**
Pin the builder in both jobs (Dependabot does not update `with:` inputs, so add a comment that it is bumped by hand):

```yaml
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
        with:
          driver-opts: image=moby/buildkit:v0.34.2@sha256:c5f8862f52499773af85bc07695b2379ef08e8002352b0df2c4864c91d78dabe
```

Or accept the moving tag and note it in `docs/architektura.md` next to `docker/dockerfile:1`.

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 5 |
| False positives removed | 0 |
| Severity adjustments | 2 |
| Cross-analysis findings | 1 |

### Cross-Analysis (Security <-> Quality)

- COMP-001 (rendered above): SEC-002 and MAINT-001 are one defect, `images.yml:66`.
- SEC-001 and DOC-001: if an image is missing from overlay `local`, the cluster pulls `:latest` from GHCR. Taken alone DOC-001 fails closed, because no `latest` tag exists. SEC-001 shows that "no `latest`" is only a workflow convention, so a write-capable actor could push it and the missing entry would then run that image silently. Separate fixes, not a composite; land DOC-001 first.
- SEC-001 and MAINT-002: with a floating builder and no cache, "Re-run all jobs" on a `main` run rebuilds the same commit and re-pushes the same `sha-<7>` with possibly different bytes. The plan's fallback is safe because it re-runs only `--failed`. Pinning the builder belongs in the same edit as any attestation.
- Coverage gap: the documentation claims `docs/architektura.md:42` and `README.md:95` present main-only publication as the control and `docs/architektura.md:43` makes the tag the T29 deploy contract. If SEC-001 is accepted as residual risk, record it in the "Obrazy" section.
- Coverage gap: no planned check covers the cancelled-run path. Add to step 4 of "Po dostarczeniu": `gh run cancel "$RUN_T"` and expect `images fail` in `gh pr checks "$PT" --required`.

### Challenged Findings

- SEC-001 — lowered from MEDIUM to LOW: only trusted write accounts can abuse it, nothing deploys from GHCR in this change, issue #29 decided the tag contract, and a signature is not enforced anywhere.
- MAINT-001 — lowered from MEDIUM to LOW: only a manual or API cancel triggers it, it needs write access, and the merge still needs an approval.
- SEC-002 — confirmed as a duplicate of MAINT-001 (same line, cause and fix); COMP-001 links them.
- MAINT-002, DOC-001 — confirmed.

### Rejected by auditors (self-falsification)

- Missing concurrency limits (zizmor `concurrency-limits`, auditor persona) — recorded plan decision, same as `ci.yml`, rejected in the T06 review.
- Floating `moby/buildkit:buildx-stable-1` as a security issue — buildx 0.36 and later check signatures.
- Floating `docker/dockerfile:1` frontend feeds published images — the same default policy applies; the Dockerfiles are outside the changed files.
- `GITHUB_TOKEN` exposed to Dockerfile `RUN` as a build secret — build-push-action adds `GIT_AUTH_TOKEN` only for a Git context; this workflow uses `context: .`.
- Public provenance `mode=max` exposes build details — recorded plan decision; no `ARG` or secret mounts.
- Public images may contain local secrets — CI checks out tracked files only; `.dockerignore` excludes `*.env`, `kubeconfig*`, `reports`.
- `docker/login-action` v4.7.0 while v4.8.0 exists — no advisories, 7-day cooldown is a recorded decision.
- `images` job inherits `contents: read` — negligible, no `permissions: {}` convention in the repo.
- A PR editing `images.yml` can fake the `images` check — the same holds for every in-repo required check, the diff is visible and review is required.
- Untrusted fork PR code in `build` — trigger is `pull_request`, read-only token, no secrets.
- Cache poisoning between PR and `main` — no `cache-from` or `cache-to`.
- 7-character `sha` tag collisions — deliberate overwrite is covered by SEC-001.
- Vulnerable Python dependencies in published images — 0 vulnerabilities; the image gate is T15.
- Duplicated `build` and `push` matrix — recorded plan decision, "zmieniaj razem" comments exist.
- README "Przed PR" line gives no local equivalent of `images` — `README.md:95` links to the contract; the plan forbids changing recipes.
- README "te same kontrole co CI" incomplete — `ci.yml` is `name: CI` and covers exactly those four; `images` is a separate workflow.
- `images` called a required check before the ruleset has it — the ruleset change is step 3 of "Po dostarczeniu", before merge.
- "Pakiety w GHCR są publiczne" not true yet — manual step after merge, verified by the anonymous pull.
- Table column "Zadanie" omits T08 for frontend — follows the per-component tags in the repository tree.
- Reference to the not yet existing overlay `cloud` (T29) — planned contract; the tree already lists it.
- `env.IMAGE_REPO` repeats the `Makefile` value — same pattern as `CI_MISE_VERSION` in `ci.yml`.
- `sha-…` tag can be overwritten by "Re-run all jobs" — same commit, digest-pinned bases, fallback uses `--failed`.
- Check name `images` equals the `make images` target — owner's decision of 2026-11-06.
- `images.yml` runs no make target, unlike the `ci.yml` header rule — that rule covers `ci.yml` only.

### Doctrine-gap candidates

- Image list repeated in about 6 places with only "zmieniaj razem" comments (both `images.yml` matrices, `Makefile` `images`, overlay `local` `images:`, the table in `docs/architektura.md`, `README.md`): no rule or check keeps them in sync.
- No rule for the provenance of project-built images: nothing requires signing them or pinning them by digest in deploy overlays, so T29 consumes mutable tags (linked to SEC-001).
- No convention for required aggregator jobs: use `always()` and fail on any result other than `success` (linked to COMP-001; T15 and T24 will extend this job).
- Nothing says whether build-time inputs (the BuildKit daemon, `docker/dockerfile:1`) must be pinned.
- Nothing says whether YAML anchors are allowed in workflows; they are the only way to remove the duplicated `build` and `push` matrix, but zizmor supports them only in beta.

### Out of scope (scope check)

None.
