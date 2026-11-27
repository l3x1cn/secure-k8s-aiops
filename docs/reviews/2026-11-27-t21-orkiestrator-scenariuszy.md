# Code Review: T21 · Orkiestrator scenariuszy awarii z etykietami

Review scope: changes since 3e09239 (8 files)

Branch `t21-orkiestrator-scenariuszy`, range `3e09239..HEAD`, delivered from `docs/plans/2026-11-24-t21-orkiestrator-scenariuszy.md` (issue #21). Auditors: security, code quality and documentation; verification by Cross-Verifier and Challenger.

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 2 |
| LOW | 5 |

No blocking defect. `make lint` is clean and `make unit` gives 140 passed. `chaos/run.py` has 92% branch coverage and passes `mypy --strict`.

Open facts from delivery verification, reflected in DOC-001: HighCPU did not fire for S1 = 4 min (CPU ratio dipped to 0.71 and 0.75 at +120 s and +150 s, which reset `for: 2m`); QA plan scenario BE-04 failed for the same reason, and its FE-01 edge 1 is a plan flaw (the tag filter is `target.tags`).

### [MEDIUM] MAINT-001: Scenario durations are written down separately 2–3 times

**ID:** MAINT-001
**Location:** `chaos/run.py:55`
**Category:** Maintainability
**Effort:** trivial

**Problem:**
The window length (`Scenario.seconds`), the injected `--seconds` literal and the timeout literal are separate numbers: S1 on line 109 (`240` and `"240"`), S2–S4 on lines 110-131, S6 as `--seconds 180` in `SPIKE` (line 55) plus `timeout=180 + COMMAND_TIMEOUT` (line 145), S7 as `+ 120` in `SCAN` (line 60) plus `timeout=120 + COMMAND_TIMEOUT` (line 160). `_execute` closes the window at `start + scenario.seconds`, while orders runs the fault for the number in the argument. The tests pin the two facts separately (`chaos/tests/test_run.py:174-182` and `:212-215`), and for S7 the script's 120 s is not asserted at all.

**Impact:**
A one-sided edit with its matching test keeps the suite green and gives a `labels.jsonl` window longer or shorter than the real fault, which is wrong ground truth for T23 and T30. A timeout copy that drifts fails loudly (kubectl timeout, `RunError`); the argument/window pair fails silently.

**Remediation:**

```python
# Before
Scenario("S1", "cpu", "orders", 240, (_fault(0, "cpu", "--seconds", "240"),)),
SPIKE = f"echo $$ > {SPIKE_PID} && exec fault-runner spike --users 50 --seconds 180"

# After
def _orders_fault(id_: str, name: str, seconds: int, *params: str) -> Scenario:
    step = _fault(0, name, "--seconds", str(seconds), *params)
    return Scenario(id_, name, "orders", seconds, (step,))

SPIKE_SECONDS = 180
SCAN_SECONDS = 120
```

Derive the `--seconds` argument and the S6 and S7 timeouts from the same number.

---

### [MEDIUM] DOC-001: Documentation says S1 = 4 min keeps HighCPU above the threshold for 204 s; the measured run contradicts it

**ID:** DOC-001
**Location:** `docs/detekcja.md:80`
**Category:** Documentation
**Effort:** easy
**Drift-class:** decision
**Fix-policy:** needs-decision

**Problem:**
`docs/detekcja.md:80` and `docs/architektura.md:355` state that `service:cpu_usage_ratio_of_limit` stays above 0.8 for the fault time minus about 36 s (204 s) and present 4 min as sufficient for `HighCPU` (`for: 2m`). The S1 window of run `t21-pelny` measured `service:cpu_usage_ratio_of_limit{service="orders"}` every 30 s from the start: 0.04, 0.01, 0.40, 1.00, 0.71, 0.75, 1.00, 1.00, 1.00, 1.00, 0.45. The dip to 0.71 and 0.75 at +120 s and +150 s reset the `for` timer; `HighCPU` stayed pending (about 105 s at most), never fired and sent no Mailpit message. QA scenario BE-04 failed twice for the same reason. The delivery plan (contingency for verification step 5) asks to record the measured values in `docs/detekcja.md`; that was not done.

**Impact:**
The S1 row of `docs/architektura.md:347` lists `HighCPU` as an expected alert, so detection evaluation (T30) can count S1 as missed by the rules. A reader of the docs believes S1 is calibrated.

**Remediation:**
Record the measured series in `docs/detekcja.md` and state that 4 min is not enough in every run. Then decide, in a separate change: lengthen S1 (the dip lasts about 60 s, so 5–6 min; the duration then changes in `chaos/run.py`, the orders default and the tables, see MAINT-001), or shorten `for` of `HighCPU`, or accept that the rules miss S1.

---

### [LOW] SEC-001: Grafana admin credentials go to whichever socket answers `localhost` first

**ID:** SEC-001
**Location:** `chaos/run.py:36`
**Category:** Security
**OWASP:** A07:2025
**CWE:** CWE-923
**Effort:** trivial

**Problem:**
`GRAFANA_URL = "http://localhost:3000"` is used with httpx basic auth (`chaos/run.py:478-480`), which sends the header on the first request. On the audited host `localhost` resolves to `::1` before `127.0.0.1`, and the kind mapping for Grafana listens only on `127.0.0.1` (`platform/kind/cluster.yaml:16-18`), so another local user can bind `[::1]:3000` and receive the admin password from the Secret `monitoring/grafana-admin` (the auditor's proof of concept showed the fake listener receiving the header). The same listener can answer 200 to every annotation POST, so no warning is printed and no region reaches Grafana.

**Impact:**
Admin access to Grafana (Loki, Prometheus, alerting) for a second unprivileged user of the same host. Not modeled in `docs/bezpieczenstwo.md` (U1–U4), the data is synthetic, hence LOW.

**Remediation:**

```python
# Before
GRAFANA_URL = "http://localhost:3000"

# After
# 127.0.0.1:3000 → NodePort 30300 Grafany (listenAddress w platform/kind/cluster.yaml).
GRAFANA_URL = "http://127.0.0.1:3000"
```

Update the comment on line 35 and the sentence "Grafana pod http://localhost:3000" in `docs/architektura.md:357`. `tests/observability/test_logs.py:29` has the same older pattern. Add an assertion in `test_every_window_gets_a_scenario_annotation` that every recorded request has `url.host == "127.0.0.1"`; today the mock transport accepts any host.

---

### [LOW] MAINT-002: Exit codes and stderr are handled in two places; Ctrl+C before the run prints nothing

**ID:** MAINT-002
**Location:** `chaos/run.py:224`
**Category:** Maintainability
**Effort:** easy

**Problem:**
`Orchestrator.run` (lines 224-243) and `main` (lines 486-491) both map `KeyboardInterrupt` and `RunError` to exit codes and stderr text. They have drifted: Ctrl+C during the run prints `interrupted` and returns 130; Ctrl+C before the run starts (Secret read, `GET /api/org`) returns 130 with empty stderr, while the plan's exit-code contract says stderr `interrupted`.

**Impact:**
A user interrupting the pre-flight gets no message. Minor, but the two copies will keep drifting.

**Remediation:**

```python
# Orchestrator.run: clean up and re-raise
except (KeyboardInterrupt, RunError):
    self._abort()
    raise

# main: map once
except RunError as exc:
    print(exc, file=sys.stderr)
    return 1
except KeyboardInterrupt:
    print("interrupted", file=sys.stderr)
    return 130
```

---

### [LOW] MAINT-003: Four contract error paths have no unit test

**ID:** MAINT-003
**Location:** `chaos/run.py:302`
**Category:** Maintainability
**Effort:** easy

**Problem:**
Never run by `chaos/tests/test_run.py` (lines 302-309, 489-491, 284, 425-428 of `chaos/run.py`): a failed cleanup command only warns and keeps the exit code; Ctrl+C before the run starts returns 130 without cleanup; S7 stops with an error when no orders pod is running; a failed `git rev-parse` returns 1 and creates no run directory. The fakes can raise `KeyboardInterrupt` only from `FakeClock.sleep`, so the first two cannot be reproduced without a hook in `FakeCluster` or `FakeGrafana`.

**Impact:**
Documented behavior (`docs/architektura.md:380-381`) can regress unnoticed; coverage is 92%, so the gap is in named paths, not the total.

**Remediation:**

```python
def test_failed_kill_is_only_a_warning(env, capsys):
    env.cluster.codes["read pid"] = [1]  # matches only the KILL command
    env.clock.interrupt_at = START + timedelta(seconds=30)

    assert start(env, "--scenarios", "S6", "--gap", "0s", "--run-id", "t21") == 130

    assert "warning: sh -c" in capsys.readouterr().err
    assert last_exec(env) == ("loadgen/fault-runner", ("fault-runner", "stop"))
```

Add similar tests: a `FakeCluster` returning empty stdout for `get pods` (S7 fails, then cleanup and exit 1); `monkeypatch.setattr(chaos_run, "REPO_ROOT", tmp_path)` for the git failure; a kubectl fake raising `KeyboardInterrupt` on `get secret` (130, no exec calls).

---

### [LOW] MAINT-004: Ctrl+C during the closing Grafana POST leaves a window without annotation

**ID:** MAINT-004
**Location:** `chaos/run.py:323`
**Category:** Maintainability
**Effort:** easy

**Problem:**
`_close` sets `self.current = None` before it writes the label (line 333) and posts the annotation (line 335). A `KeyboardInterrupt` inside the POST (up to the 10 s httpx timeout) on the normal `_execute` path, where SIGINT is not ignored, reaches `run()`; `_abort` finds `current` empty and does nothing, so the annotation is never sent and nothing warns.

**Impact:**
The label stays in `labels.jsonl` (ground truth intact), but the window has no region in Grafana, against `docs/architektura.md:381`. The time window is one HTTP round-trip.

**Remediation:**
Do the label write and the POST inside the SIGINT-ignored section that `_abort` uses (`chaos/run.py:292-300`), or catch `KeyboardInterrupt` around `_annotate`, finish the POST and re-raise.

---

### [LOW] MAINT-005: Default `--gap`, stdout progress lines and annotation text are not asserted by any test

**ID:** MAINT-005
**Location:** `chaos/tests/test_run.py:161`
**Category:** Maintainability
**Effort:** easy

**Problem:**
The only test that runs gaps (`test_full_run_writes_seven_windows_separated_by_gap`) passes `--gap 10m` explicitly, so the 600 s default never runs. `test_every_window_gets_a_scenario_annotation` (lines 193-206) checks `tags`, `time`, `timeEnd` and the `Authorization` header but not `text`, and no test captures stdout, so the `run`/`start`/`end` lines are unchecked.

**Impact:**
Changing the default to another value or changing the documented text and output format keeps all 26 tests green although the docs (`docs/architektura.md:357-368`) promise them.

**Remediation:**
Drop `"--gap", "10m"` from the full-run test so it covers the default; in the annotation test assert `env.grafana.annotations[0]["text"] == "S3 errors → orders, przebieg t21"` and use `capsys` to assert the `start S3 errors orders` and `end S7 scan orders` lines.

---

## Verification Summary

**Method:** Cross-domain correlation and adversarial review (Cross-Verifier + Challenger)

| Metric | Count |
|--------|-------|
| Findings verified | 7 |
| False positives removed | 0 |
| Severity adjustments | 0 |
| Cross-analysis findings | 0 |

### Cross-Analysis (Security <-> Quality)
- SEC-001 and MAINT-004 produce the same silent symptom on one path: an impostor on `[::1]:3000` that answers 200 swallows annotations without a warning, and Ctrl+C during the POST loses one without a warning. Both stay LOW and need separate edits.
- SEC-001 and MAINT-005: the request that carries the credentials is tested for what it sends, not for where it goes (`httpx.MockTransport` accepts any host), so the SEC-001 fix has no regression guard until the host is asserted.
- MAINT-001 and DOC-001: if S1 is lengthened, the duration has to change in `chaos/run.py:109`, `services/orders/src/orders/faults.py:236`, the tests, `docs/architektura.md` and `docs/detekcja.md`; consolidating the literals first (MAINT-001) removes the one-sided edit risk. No composite finding: each needs its own change.
- Coverage gap noted by the Cross-Verifier: `docs/architektura.md:357` carries the `localhost:3000` wording that SEC-001 changes; the fix has to update it.

### Challenged Findings
- None removed or downgraded. The Challenger corrected two details: the timeout copies in MAINT-001 fail loudly (only the argument/window pair fails silently), and in MAINT-005 three tests omit `--gap` but all exit before any gap sleep.

### Rejected by auditors (self-falsification)
- Security: semgrep and bandit subprocess, `/tmp` PID file and test-literal hits — argument lists without a shell, PID files in a private `emptyDir`, test placeholders.
- Security: command injection through the orders pod IP — the IP reaches the script as a quoted positional `$1`.
- Security: path traversal through `--run-id` — the regex allows no `/` and no leading `.`.
- Security: Grafana admin account used for annotations, basic auth over loopback HTTP, CPU fault default 120→240 s, stale PID kill race, raw pod stderr, uncaught `mkdir` race, secret bytes in a decode error — reasons in the auditor report (operator already holds the Secret; token check and 3600 s bound unchanged; no security effect).
- Security: three CVEs in `uv.lock` (opentelemetry-api, soupsieve, tornado) — `uv.lock` is not changed by this branch.
- Quality: Orchestrator size and SRP, six constructor parameters, truth window for a failed scenario, real `git` in unit tests, `raise … from None`, `print` instead of logging, test annotations under `mypy --strict`, duplicated secret read, the `Step.orders_ip` flag, non-project ruff rules — approved single-file design and plan decisions.
- Documentation: `run.json` and `dashboardUID` drift hits, backlog and README status, missing `Test:` line, run-id leading character, README dashboard sentence, README manual PolicyDenied demo, threat-model wording — generated file and by-design omissions.

### Doctrine-gap candidates
- No rule says which address host-side clients use to reach loopback-only services (`localhost` or `127.0.0.1`), and the threat model does not say whether other local users on the host are in scope (behind SEC-001).
- No rule says whether unit tests may depend on host binaries other than kubectl, such as `git`.

### Out of scope (scope check)
None.
