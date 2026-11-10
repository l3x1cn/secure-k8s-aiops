# T13 · Pod Security Admission i securityContext (issue #13)

## Context

Issue #13 (T13, R2 Bezpieczeństwo, Sprint 2). Zależy od T04 i T05, oba scalone. Cel: kontenery bez zbędnych uprawnień, a klaster odrzuca pody uprzywilejowane. Zakres z issue:
- etykiety namespace'ów według sekcji „Namespace'y i Pod Security” w `docs/architektura.md`: `enforce`, `warn` i `audit` = restricted; monitoring = privileged z komentarzem uzasadniającym;
- securityContext wszystkich własnych workloadów:
  - `runAsNonRoot`, `readOnlyRootFilesystem` (z emptyDir na `/tmp`), `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`;
  - własne obrazy: `runAsUser: 10001`; obrazy zewnętrzne (Locust, curl): ich domyślny UID bez roota;
- `tests/security/test_pod_security.py`: `kubectl apply --dry-run=server` uprzywilejowanego poda w shop kończy się błędem `violates PodSecurity "restricted`.

Kryteria akceptacji:
1. Test przechodzi, a wszystkie własne pody działają z nowym securityContext.
2. `trivy config deploy/` nie zgłasza HIGH ani CRITICAL dla własnych manifestów.

Decyzje właściciela (2026-11-10):
- intruder zostaje na UID 10001 (stan z T12) zamiast domyślnego `curl_user` (uid 100). Kontrakt w architekturze dostaje regułę dla obrazów zewnętrznych, a PR opisuje odstępstwo od tekstu issue;
- test obejmuje odrzucenie uprzywilejowanego poda w czterech namespace'ach restricted oraz kontrakt securityContext każdego działającego własnego poda.

Stan docelowy:
- `deploy/base/namespaces.yaml`: po trzy etykiety PSA na namespace (15 etykiet zamiast 5) i uzasadnienie wyjątku monitoring;
- fault-runner i intruder z `/tmp` z `emptyDir`, jak frontend i orders;
- `tests/security/test_pod_security.py`: 5 testów, marker `security`. Na klastrze z `make up` cały `tests/security` daje `92 passed` (74 RBAC + 13 NetworkPolicy + 5 Pod Security);
- kontrakt w `docs/architektura.md` i linia testów w README.

### Ustalone fakty (sprawdzone 2026-11-10)

- Repozytorium: gałąź `main`, HEAD `d44b04b` (T12 scalony w #52), `git status --short` pusty. Issue #13 nie ma komentarzy. PR #51 (T11) i #52 (T12) zatwierdził `DreadGoblin`; #52 scalił `l3x1cn`.
- Większość securityContext już jest (T05, T08, T12):
  - frontend i orders (`deploy/base/{frontend,orders}/deployment.yaml`) mają komplet:
    - pod: `runAsNonRoot: true`, `runAsUser`/`runAsGroup` 10001, `seccompProfile: RuntimeDefault`;
    - kontener: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`;
    - wolumen `tmp` (`emptyDir`, `sizeLimit: 16Mi`) na `/tmp`;
  - fault-runner (`deploy/base/fault-runner/deployment.yaml`): to samo plus `fsGroup: 10001`, bez `/tmp`. W działającym podzie `python -c 'import tempfile; print(tempfile.gettempdir())'` kończy się błędem `FileNotFoundError: [Errno 2] No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp', '/']`. Kod fault-runnera (`chaos/src/fault_runner/cli.py`) nie używa dziś `tempfile`;
  - intruder (`deploy/base/intruder/deployment.yaml`): pola jak frontend, bez `/tmp`. Linia 24 ma komentarz „Obraz działa jako curl_user (uid 100); 10001 jak w pozostałych workloadach (Trivy KSV-0020, KSV-0021).”
    - Konfiguracja obrazu `curlimages/curl` (crictl): `User: curl_user`, nazwa zamiast liczby. `/etc/passwd`: `curl_user:x:100:101`.
    - W podzie `id` → `uid=10001 gid=10001`, a `touch /probe-t13` → `Read-only file system`;
  - Dockerfile `services/frontend`, `services/orders` i `chaos`: `USER 10001:10001`.
- `deploy/base/namespaces.yaml` ma tylko `pod-security.kubernetes.io/enforce`: restricted w shop, loadgen, aiops i intruder, privileged w monitoring z komentarzem „Wyjątek z tabeli: node-exporter (T16) i Alloy (T17) potrzebują dostępu do hosta.” Nagłówek pliku: „Etykieta enforce według tabeli; warn, audit i test Pod Security dodaje T13.” To samo zdanie jest w `docs/architektura.md:60`.
- Klaster `kind-secure-k8s-aiops` działa z manifestami z `main` (4 własne pody `Running`). Serwer API nie ma flag audytu, a z wtyczek admission włączono jawnie tylko `--enable-admission-plugins=NodeRestriction`. PodSecurity działa więc z domyślną konfiguracją: privileged we wszystkich trybach. Wyniki `--dry-run=server` (nic nie zapisuje):
  - pod z `securityContext.privileged: true` w shop, loadgen, aiops i intruder → kod 1:

    ```text
    Error from server (Forbidden): error when creating "STDIN": pods "t13-privileged" is forbidden: violates PodSecurity "restricted:latest": privileged (container "probe" must not set securityContext.privileged=true), allowPrivilegeEscalation != false (...), unrestricted capabilities (...), runAsNonRoot != true (...), seccompProfile (...)
    ```

    W monitoring ten sam pod daje `pod/t13-privileged created (server dry run)`;
  - Deployment z takim szablonem w shop → kod 0 i `Warning: would violate PodSecurity "restricted:latest": ...`, choć shop nie ma etykiety `warn`. W `default` i monitoring ostrzeżenia nie ma.
    - Powód: `PolicyToEvaluate` w `staging/src/k8s.io/pod-security-admission/api/helpers.go` (release-1.36, linie 228–234). Bez etykiety `warn` bierze poziom `warn` z `enforce`, gdy ten jest bardziej restrykcyjny.
    - `audit` takiego mechanizmu nie ma (domyślnie privileged), a kind nie zapisuje logu audytu.
  - Wniosek: jawne `warn: restricted` nie zmienia zachowania w kind, a `audit: restricted` zmienia tylko zdarzenia audytu. Test może dowieść `enforce`; etykiety `warn` i `audit` sprawdza Verification.
- Prototyp na kopii `deploy/` poza repo, z dokładnie tymi zmianami co w Task 2:
  - `scripts/manifests.sh` → `Summary: 38 resources found parsing stdin - Valid: 38` (tyle samo co na `main`);
  - `trivy config --severity HIGH,CRITICAL --exit-code 1` → kod 0, a uwagi są takie same jak na `main`:
    - frontend, orders i fault-runner po 3: KSV-0013 MEDIUM (obraz bez tagu w base), KSV-0110 LOW (namespace z kustomization), KSV-0125 MEDIUM (rejestr);
    - intruder 2: KSV-0110 i KSV-0125;
    - namespaces, RBAC, NetworkPolicy i Service: 0;
  - `kustomize build deploy/overlays/local | kubectl apply --dry-run=server -f -` na klastrze daje:
    - 5 namespace'ów i Deploymenty `intruder` i `fault-runner` jako `configured`;
    - reszta `unchanged`;
    - zero ostrzeżeń PodSecurity;
  - `kustomize build deploy/overlays/local | grep -c 'pod-security.kubernetes.io/'` → `15` (na `main` `5`), a `grep -c 'mountPath: /tmp'` → `4` (na `main` `2`).
- Prototyp testu z Task 1:
  - `ruff format --check` i `ruff check` z konfiguracją repo przechodzą;
  - na klastrze z `main` daje `1 failed, 4 passed`: pada `test_own_containers_are_hardened` z dokładnie dwiema liniami, `intruder/intruder-…/intruder: /tmp bez wolumenu emptyDir` i `loadgen/fault-runner-…/fault-runner: /tmp bez wolumenu emptyDir`;
  - `hardening_problems` na szablonach z dry-runu prototypu deploy zwraca pustą listę dla wszystkich 4 Deploymentów.
- `tests/security`: 87 testów (74 RBAC + 13 NetworkPolicy). Każdy moduł ma własny helper `kubectl()` i fixture `cluster`, `pytestmark = pytest.mark.security` i `KUBE_CONTEXT` ze zmiennej środowiskowej; `conftest.py` nie ma. Przegląd T12 zapisał duplikację helperów jako kandydata na regułę, nie jako uwagę.
- Chart `prometheus-node-exporter` (`values.yaml` w `prometheus-community/helm-charts`, gałąź main) ma `hostNetwork: true`, `hostPID: true`, `hostRootFsMount.enabled: true` i montowania `/proc` i `/sys` z hosta. Poziom baseline zabrania hostNetwork, hostPID i hostPath.

## Warunek wstępny (główny agent, przed startem delivery)

W korzeniu repozytorium:

```bash
git status --short                      # oczekiwane: pusto
git switch main && git pull --ff-only
mise exec -- kind get clusters          # oczekiwane: secure-k8s-aiops; inaczej make up
make deploy                             # klaster z manifestami z main; idempotentne
git switch -c t13-pod-security
```

Taski nie dotykają klastra, więc do `make deploy` w kroku 3 Verification działają manifesty z `main`, których wymaga krok 2.

## Approach

Task 1 należy do stosu Python. Task 2 i 3 należą do stosu „pozostałe” (YAML, Markdown). Kolejność 1 → 2 → 3:
- najpierw test; na klastrze z `main` pada w `test_own_containers_are_hardened` (krok 2 Verification);
- potem manifesty, po których test przechodzi;
- na końcu kontrakt.

Taski sprawdzają tylko to, co działa bez klastra: `make lint`, `make unit`, `make manifests`, Trivy i zbieranie testów. Przebiegi na klastrze są w Verification.

Decyzje wspólne:
- Każdy namespace z tabeli poza kube-system ma trzy etykiety `pod-security.kubernetes.io/{enforce,warn,audit}` z tym samym poziomem. Etykiet `*-version` nie ma (domyślnie `latest`, jak w T04).
- monitoring ma privileged we wszystkich trzech trybach (dosłownie „monitoring = privileged”). Ostrzeżenia o zamierzonych wyjątkach node-exportera przy każdym `make up` byłyby szumem.
- `/tmp` z `emptyDir` (`sizeLimit: 16Mi`, jak frontend i orders) dostaje każdy własny workload, czyli dochodzi w fault-runner i intruder. Python bez zapisywalnego katalogu tymczasowego kończy się błędem `tempfile`.
- intruder zostaje na `runAsUser`/`runAsGroup` 10001, a komentarz w linii 24 jego manifestu się nie zmienia. Regułę dla obrazów zewnętrznych zapisuje Task 3.
- Bez zmian: manifesty frontend i orders, Dockerfile, Makefile, CI. Bramka Trivy w CI to T15, a `make test-security` to T26.

### Task 1: Test Pod Security na klastrze
**Commit:** test(security): odrzucenie uprzywilejowanego poda i kontrakt securityContext własnych podów (T13)

**Files:**
- Test: `tests/security/test_pod_security.py`

1. Utwórz `tests/security/test_pod_security.py` z treścią poniżej. Jest sformatowana ruffem 0.17.3; nie zmieniaj formatowania. Decyzje w tej treści:
   - Wzór modułu z `tests/security/test_rbac.py`: własny `kubectl()` (tu z parametrem `stdin`), `get_json()`, fixture `cluster` (brak kubectl albo klastra to `pytest.fail`, nie pominięcie), marker `security`, `KUBE_CONTEXT` ze zmiennej. Bez klienta Pythona dla Kubernetesa i bez `conftest.py`.
   - `test_privileged_pod_is_rejected` dla shop, loadgen, aiops i intruder. Issue wymienia tylko shop, ale tabela daje restricted we wszystkich czterech.
     - Manifest poda to JSON przez stdin do `kubectl apply --dry-run=server -f -`, więc nic nie powstaje.
     - Obraz `ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev`: dry-run go nie pobiera, a test nie powiela pinu obrazu intrudera.
     - Asercje:
       - kod różny od 0;
       - `violates PodSecurity "restricted:` w stderr, czyli poziom z etykiety `enforce`, więc `baseline` też oblewa test;
       - `must not set securityContext.privileged=true`, czyli odrzucenie z właściwego powodu.
   - `test_own_containers_are_hardened` czyta wszystkie pody z etykietą `app.kubernetes.io/part-of=secure-k8s-aiops` bez `deletionTimestamp`.
     - Pusty wynik oblewa test. Sprawdza `initContainers` i `containers`.
     - Wartość kontenera ma pierwszeństwo przed wartością poda (`runAsNonRoot`, `runAsUser`, `seccompProfile`).
     - UID 10001 jest wymagany tylko dla obrazów z prefiksem `ghcr.io/l3x1cn/secure-k8s-aiops/`.
     - `/tmp` musi być zamontowany z wolumenu `emptyDir`; `sizeLimit` nie jest sprawdzany.
   - Etykiet `warn` i `audit` test nie sprawdza, bo w kind nie mają obserwowalnego skutku; pokazuje je tylko `kubectl get ns -L` w Verification i dowodzie (alternatywa w „Assumptions”).
   - Kontrakt dla Task 2: każdy kontener w fault-runner i intruder montuje `/tmp` z wolumenu `emptyDir`.

```python
# Pod Security (T13) na działającym klastrze: PSA restricted odrzuca uprzywilejowany
# pod, a kontenery własnych workloadów mają securityContext z kontraktu
# (docs/architektura.md, sekcja „Namespace'y i Pod Security”; etykiety PSA
# w deploy/base/namespaces.yaml). Pod próbny idzie przez `kubectl apply
# --dry-run=server`: przechodzi admission, ale nic nie powstaje w klastrze.
# Etykiet warn i audit test nie sprawdza, bo w kind nie mają obserwowalnego skutku:
# bez etykiety warn PSA bierze poziom z enforce, a audit działa tylko z logiem
# audytu, którego kind nie ma. Pokazuje je `kubectl get ns -L
# pod-security.kubernetes.io/warn,pod-security.kubernetes.io/audit`.
# Uruchomienie: uv run --locked pytest tests/security/test_pod_security.py
# (kubectl z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import json
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.security

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
PART_OF = "app.kubernetes.io/part-of=secure-k8s-aiops"
# Namespace'y z PSA restricted (tabela w architekturze); monitoring ma privileged.
RESTRICTED_NAMESPACES = ["shop", "loadgen", "aiops", "intruder"]
# Obrazy budowane w projekcie (IMAGE_REPO w Makefile, USER 10001:10001).
OWN_IMAGE_REPO = "ghcr.io/l3x1cn/secure-k8s-aiops/"
OWN_UID = 10001
# Dry-run nie pobiera obrazu, więc tag :dev wystarcza także poza kind.
PROBE_IMAGE = f"{OWN_IMAGE_REPO}orders:dev"


def kubectl(
    *args: str, stdin: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        pytest.fail(f"kubectl {command}: kod {result.returncode}, {result.stderr}")
    return result


def get_json(*args: str) -> dict:
    return json.loads(kubectl("get", *args, "-o", "json").stdout)


def privileged_pod(namespace: str) -> str:
    # privileged: true daje kontenerowi wszystkie capabilities i urządzenia hosta.
    return json.dumps(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "t13-privileged", "namespace": namespace},
            "spec": {
                "containers": [
                    {
                        "name": "probe",
                        "image": PROBE_IMAGE,
                        "securityContext": {"privileged": True},
                    }
                ]
            },
        }
    )


def hardening_problems(pod: dict, container: dict) -> list[str]:
    """Odstępstwa kontenera od kontraktu T13; pusta lista oznacza zgodność."""
    pod_context = pod["spec"].get("securityContext", {})
    context = container.get("securityContext", {})
    # Pola obecne w obu miejscach: wartość kontenera ma pierwszeństwo.
    run_as_non_root = context.get("runAsNonRoot", pod_context.get("runAsNonRoot"))
    run_as_user = context.get("runAsUser", pod_context.get("runAsUser"))
    seccomp = context.get("seccompProfile", pod_context.get("seccompProfile", {}))
    capabilities = context.get("capabilities", {})
    volumes = {volume["name"]: volume for volume in pod["spec"].get("volumes", [])}
    tmp = [
        mount["name"]
        for mount in container.get("volumeMounts", [])
        if mount["mountPath"] == "/tmp"
    ]

    problems = []
    if run_as_non_root is not True:
        problems.append("runAsNonRoot != true")
    # Obraz zewnętrzny może mieć inny UID; runAsNonRoot i tak wyklucza roota.
    if container["image"].startswith(OWN_IMAGE_REPO) and run_as_user != OWN_UID:
        problems.append(f"runAsUser {run_as_user} != {OWN_UID}")
    if context.get("readOnlyRootFilesystem") is not True:
        problems.append("readOnlyRootFilesystem != true")
    if context.get("allowPrivilegeEscalation") is not False:
        problems.append("allowPrivilegeEscalation != false")
    if capabilities.get("drop") != ["ALL"] or capabilities.get("add"):
        problems.append(f"capabilities {capabilities} zamiast drop: [ALL] bez add")
    if seccomp.get("type") != "RuntimeDefault":
        problems.append(f"seccompProfile {seccomp} zamiast RuntimeDefault")
    if not tmp or "emptyDir" not in volumes[tmp[0]]:
        problems.append("/tmp bez wolumenu emptyDir")
    return problems


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    result = kubectl("get", "--raw", "/readyz", check=False)
    if result.returncode != 0:
        pytest.fail(f"Klaster {KUBE_CONTEXT} niedostępny (make up): {result.stderr}")


@pytest.mark.parametrize("namespace", RESTRICTED_NAMESPACES)
def test_privileged_pod_is_rejected(namespace):
    result = kubectl(
        "apply",
        "--dry-run=server",
        "-f",
        "-",
        stdin=privileged_pod(namespace),
        check=False,
    )
    assert result.returncode != 0, f"pod przyjęty: {result.stdout}"
    # Komunikat podaje poziom enforce, więc baseline w etykiecie też oblewa test.
    assert 'violates PodSecurity "restricted:' in result.stderr, result.stderr
    assert "must not set securityContext.privileged=true" in result.stderr


def test_own_containers_are_hardened():
    listed = get_json("pods", "-A", "-l", PART_OF)
    pods = [p for p in listed["items"] if "deletionTimestamp" not in p["metadata"]]
    assert pods, f"brak podów z etykietą {PART_OF} (make deploy)"
    problems = []
    for pod in pods:
        namespace, name = pod["metadata"]["namespace"], pod["metadata"]["name"]
        spec = pod["spec"]
        for container in spec.get("initContainers", []) + spec["containers"]:
            for problem in hardening_problems(pod, container):
                problems.append(f"{namespace}/{name}/{container['name']}: {problem}")
    assert not problems, "\n".join(problems)
```

2. Sprawdź w korzeniu repo:
   - `make lint` → kod 0;
   - `make unit` → kod 0, liczba testów bez zmian (`testpaths` nie obejmuje `tests/`);
   - `mise exec -- uv run --locked pytest tests/security/test_pod_security.py --collect-only -q` → `5 tests collected`.

### Task 2: Etykiety PSA i /tmp w fault-runner i intruder
**Commit:** feat(deploy): etykiety Pod Security warn i audit oraz /tmp z emptyDir w fault-runner i intruder (T13)

**Files:**
- Modify: `deploy/base/namespaces.yaml`
- Modify: `deploy/base/fault-runner/deployment.yaml`
- Modify: `deploy/base/intruder/deployment.yaml`

1. Zastąp całą treść `deploy/base/namespaces.yaml`. Nazwy, kolejność obiektów i wartości `enforce` zostają; dochodzą `warn`, `audit` i nowe komentarze:

```yaml
# Namespace'y i poziomy Pod Security z docs/architektura.md („Namespace'y i Pod Security”), T04 i T13;
# kube-system zostaje bez zmian. Każdy namespace ma trzy etykiety PSA z tym samym poziomem:
# - enforce odrzuca pod, który łamie poziom;
# - warn ostrzega przy kubectl apply Deploymentu, którego szablon poda łamie poziom (enforce sprawdza tylko pody);
# - audit dopisuje naruszenie do zdarzenia w logu audytu serwera API (kind nie ma logu audytu).
# Bez etykiety PSA bierze warn z enforce, a audit z konfiguracji serwera API, więc wszystkie trzy są jawne.
# Test: tests/security/test_pod_security.py.
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: loadgen
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: aiops
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: intruder
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    # Wyjątek z tabeli. PSA działa na cały namespace, a node-exporter (T16: hostNetwork, hostPID, hostPath /, /proc
    # i /sys) oraz Alloy (T17: logi z węzła) potrzebują dostępu do hosta, którego zabrania już poziom baseline.
    # warn i audit też privileged: ostrzeżenia o zamierzonych wyjątkach przy każdym make up byłyby szumem.
    # Pody tworzą tu tylko charty z make up i ich operatory; zespół ma w RBAC tylko odczyt (T11).
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/warn: privileged
    pod-security.kubernetes.io/audit: privileged
```

2. `deploy/base/fault-runner/deployment.yaml`:
   - po montowaniu `fault-token` w `volumeMounts` kontenera (linie 58–60) dopisz:

     ```yaml
                 - name: tmp
                   mountPath: /tmp
     ```

   - po wolumenie `fault-token` w `volumes` poda (linie 62–68) dopisz:

     ```yaml
             - name: tmp
               emptyDir:
                 sizeLimit: 16Mi
     ```

   Wcięcia jak w `deploy/base/frontend/deployment.yaml`, linie 66–72: elementy `volumeMounts` mają 12 spacji, elementy `volumes` 8. Pozostałe linie bez zmian.
3. `deploy/base/intruder/deployment.yaml`: po `securityContext` kontenera (linie 47–51, ostatnia `drop: [ALL]`) dopisz na końcu pliku:

```yaml
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 16Mi
```

   `volumeMounts` należy do kontenera (10 spacji), a `volumes` do specyfikacji poda (6 spacji), jak w frontend. Komentarz o UID w linii 24 i `runAsUser`/`runAsGroup` 10001 zostają.
4. Sprawdź w korzeniu repo:
   - `make manifests` → `Summary: 38 resources found parsing stdin - Valid: 38`;
   - `mise exec -- trivy config --skip-version-check --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0;
   - `mise exec -- kustomize build deploy/overlays/local | grep -c 'pod-security.kubernetes.io/'` → `15`;
   - `mise exec -- kustomize build deploy/overlays/local | grep -c 'mountPath: /tmp'` → `4`.

### Task 3: Kontrakt Pod Security w architekturze i README
**Commit:** docs: kontrakt Pod Security i securityContext (T13) w architekturze i README

**Files:**
- Modify: `docs/architektura.md`
- Modify: `README.md`

1. `docs/architektura.md`: zastąp linie 49–60, od nagłówka `## Namespace'y i Pod Security` do akapitu kończącego się „a `warn`, `audit` i test dodaje T13.”, treścią poniżej. Sekcja `## RBAC` (linia 62) i dalsze zostają bez zmian.

```markdown
## Namespace'y i Pod Security

| Namespace | Zawartość | PSA (`enforce`, `warn`, `audit`) |
|---|---|---|
| shop | frontend, orders | restricted |
| loadgen | locust, fault-runner | restricted |
| aiops | anomaly-detector | restricted |
| intruder | intruder | restricted |
| monitoring | kube-prometheus-stack, Loki, Alloy, Mailpit | privileged; wyjątek: node-exporter i Alloy potrzebują dostępu do hosta |
| kube-system | Cilium, Hubble, CoreDNS | bez zmian |

Namespace'y opisuje `deploy/base/namespaces.yaml` (T04, T13); `make up` stosuje go przed sekretami i chartami. Każdy namespace z tabeli poza kube-system ma trzy etykiety `pod-security.kubernetes.io/<tryb>` z poziomem z tabeli:
- `enforce` odrzuca pod, który łamie poziom;
- `warn` dodaje ostrzeżenie `would violate PodSecurity` do odpowiedzi na `kubectl apply` Deploymentu, którego szablon poda łamie poziom. `enforce` sprawdza tylko pody, więc taki Deployment powstaje, a odrzucone pody widać dopiero w zdarzeniach ReplicaSetu;
- `audit` dopisuje naruszenie do zdarzenia w logu audytu serwera API; kind nie ma logu audytu.

Bez etykiety PSA bierze `warn` z `enforce`, a `audit` z konfiguracji serwera API (w kind privileged). Jawne etykiety dają te same poziomy w każdym klastrze, także w overlayu cloud (T29).

PSA działa na cały namespace, więc w monitoring każdy pod może być uprzywilejowany. Wymagają tego node-exporter (T16: `hostNetwork`, `hostPID`, hostPath `/`, `/proc` i `/sys`) i Alloy (T17: logi z węzła), a zabrania już poziom baseline. `warn` i `audit` mają tam też privileged, bo ostrzeżenia o zamierzonych wyjątkach przy każdym `make up` byłyby szumem. Pody w monitoring tworzą tylko charty z `make up` i ich operatory; zespół ma w RBAC tylko odczyt (T11).

Kontenery własnych workloadów (tabela w sekcji „RBAC”) mają securityContext (T13) według wzoru `deploy/base/frontend/deployment.yaml`:
- pod: `runAsNonRoot: true`, `runAsUser` i `runAsGroup` 10001, `seccompProfile.type: RuntimeDefault`;
- kontener: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]` bez `add`;
- jedyny zapisywalny katalog to `/tmp` z wolumenu `emptyDir` z `sizeLimit: 16Mi`.

Obrazy budowane w projekcie mają `USER 10001:10001`. Obraz zewnętrzny, który działa z dowolnym UID, też dostaje 10001 (intruder: obraz curl ma użytkownika `curl_user`, uid 100). Obraz zewnętrzny, który z UID 10001 nie działa, dostaje swój domyślny UID bez roota, wpisany liczbą: kubelet nie uruchomi kontenera z `runAsNonRoot: true`, gdy obraz podaje użytkownika nazwą. PSA restricted nie wymaga `readOnlyRootFilesystem`, UID 10001 ani `/tmp`; pilnuje ich test.

Test: `tests/security/test_pod_security.py` (marker `security`); na działającym klastrze `uv run --locked pytest tests/security/test_pod_security.py`. Sprawdza:
- `kubectl apply --dry-run=server` poda z `privileged: true` w shop, loadgen, aiops i intruder kończy się błędem `violates PodSecurity "restricted:latest"`;
- każdy kontener podów z etykietą `app.kubernetes.io/part-of=secure-k8s-aiops` (poza usuwanymi) ma `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` bez `add`, `seccompProfile.type: RuntimeDefault` i `/tmp` z wolumenu `emptyDir`. Kontener z obrazem projektu ma też `runAsUser` 10001.

Nowy workload z tą etykietą test obejmuje bez zmian w kodzie testu. `runAsGroup`, `sizeLimit` i brak innych zapisywalnych montowań sprawdza tylko review.
```

2. `README.md`, linia 68 (blok „Testy bezpieczeństwa na działającym klastrze”): zastąp komentarz po poleceniu, tak żeby linia brzmiała:

```bash
uv run --locked pytest tests/security  # RBAC (T11), NetworkPolicy (T12), Pod Security (T13): konta usług, role zespołu, przepływy, odrzucenie poda uprzywilejowanego, securityContext podów
```

3. Sprawdź w korzeniu repo:
   - `make lint` → kod 0;
   - `grep -rn 'dodaje T13' docs/architektura.md deploy/` → brak wyników;
   - `grep -c 'pod-security.kubernetes.io/<tryb>' docs/architektura.md` → `1` (zdanie z nowej sekcji).

## Critical files & anchors

- `deploy/base/fault-runner/deployment.yaml`, linie 57–68: `volumeMounts` z `fault-token` i `volumes`; `tmp` dochodzi jako drugi element obu list. Dwa poziomy wcięcia: kontener (10) i pod (6).
- `deploy/base/intruder/deployment.yaml`, linie 47–51: koniec pliku. Kontener nie ma dziś `volumeMounts`, a pod nie ma `volumes`.
- `deploy/base/frontend/deployment.yaml`, linie 61–72: wzór securityContext, `volumeMounts` i `volumes` dla obu zmian.
- `docs/architektura.md`, linie 49–60: zastępowana sekcja; linia 51 to nagłówek tabeli z kolumną „PSA enforce”, linia 60 to zdanie o T13.
- `tests/security/test_rbac.py`, linie 103–117 i 148–154: styl `kubectl()`, `get_json()` i fixture `cluster`, skopiowany do nowego modułu.

## Verification

Korzeń repozytorium, gałąź `t13-pod-security` z Taskami 1–3, klaster `kind-secure-k8s-aiops`, na którym do kroku 3 działają manifesty z `main`. W jednej sesji bash:

```bash
set -o pipefail
K="mise exec -- kubectl --context kind-secure-k8s-aiops"
PYTEST="mise exec -- uv run --locked pytest"
mkdir -p reports
```

1. Bez klastra:
   - `make lint && make unit && make manifests` → kod 0; `manifests` daje `Valid: 38`;
   - `mise exec -- trivy config --skip-version-check --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0;
   - `mise exec -- trivy config --skip-version-check deploy/ | tee reports/t13-trivy.txt` → w „Report Summary” frontend, orders i fault-runner mają po 3, intruder 2, a pozostałe pliki 0. Uwagi to wyłącznie KSV-0013, KSV-0110 i KSV-0125, jak na `main`.
2. Test wykrywa brak `/tmp` (przed `make deploy`):

   ```bash
   $PYTEST tests/security/test_pod_security.py -v | tee reports/t13-przed.txt
   $K -n loadgen exec deploy/fault-runner -- python -c 'import tempfile; print(tempfile.gettempdir())'
   ```

   - pytest → `1 failed, 4 passed`. Cztery `test_privileged_pod_is_rejected[...]` przechodzą. `test_own_containers_are_hardened` pada z dokładnie dwiema liniami `intruder/intruder-…/intruder: /tmp bez wolumenu emptyDir` i `loadgen/fault-runner-…/fault-runner: /tmp bez wolumenu emptyDir`;
   - exec → `FileNotFoundError: [Errno 2] No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp', '/']`.
3. Wdrożenie T13:

   ```bash
   make deploy
   $K get ns shop loadgen aiops intruder monitoring -L pod-security.kubernetes.io/enforce,pod-security.kubernetes.io/warn,pod-security.kubernetes.io/audit
   $PYTEST tests/security -v | tee reports/t13-po.txt
   $K -n loadgen exec deploy/fault-runner -- python -c 'import tempfile; print(tempfile.gettempdir())'
   $K -n loadgen exec deploy/fault-runner -- fault-runner stop
   $K -n intruder exec deploy/intruder -- sh -c 'id; touch /probe; touch /tmp/probe && rm /tmp/probe && echo tmp-ok'
   ```

   - `make deploy` → kod 0. Wypisuje 5 namespace'ów i Deploymenty `fault-runner` i `intruder` jako `configured`, bez żadnej linii `Warning: would violate PodSecurity`. Rollout kończy się w shop, loadgen, aiops i intruder;
   - etykiety: shop, loadgen, aiops i intruder mają `restricted` w kolumnach ENFORCE, WARN i AUDIT, a monitoring `privileged` we wszystkich trzech;
   - pytest → `92 passed` (74 + 13 + 5); bez wyjścia do internetu `89 passed, 3 skipped`;
   - fault-runner: `/tmp`, potem `{"stopped":null}`;
   - intruder: `uid=10001 gid=10001 groups=10001`, `touch: /probe: Read-only file system`, `tmp-ok`.
4. Mutacje (każda kończy się przywróceniem):
   - Etykiety PSA:

     ```bash
     $K label ns shop pod-security.kubernetes.io/enforce=baseline --overwrite
     $K label ns intruder pod-security.kubernetes.io/enforce=privileged --overwrite
     $PYTEST tests/security/test_pod_security.py -v | tee reports/t13-mutacja-psa.txt
     make namespaces
     ```

     - pytest → `2 failed, 3 passed`;
     - `test_privileged_pod_is_rejected[shop]` pada, bo stderr zawiera `violates PodSecurity "baseline:latest"`;
     - `test_privileged_pod_is_rejected[intruder]` pada z `pod przyjęty: pod/t13-privileged created (server dry run)`;
     - `make namespaces` → `namespace/shop configured`, `namespace/intruder configured`, a `$K get ns shop intruder -L pod-security.kubernetes.io/enforce` → `restricted` w obu.
   - securityContext poza PSA:

     ```bash
     $K -n loadgen patch deployment fault-runner --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem","value":false}]'
     $K -n loadgen rollout status deployment/fault-runner --timeout=2m
     $PYTEST tests/security/test_pod_security.py -v | tee reports/t13-mutacja-rofs.txt
     make deploy
     $PYTEST tests/security/test_pod_security.py
     ```

     - patch przechodzi bez ostrzeżenia PodSecurity, bo restricted nie wymaga `readOnlyRootFilesystem`;
     - pytest → `1 failed, 4 passed` z linią `loadgen/fault-runner-…/fault-runner: readOnlyRootFilesystem != true`;
     - po `make deploy` → `5 passed`.
5. Od zera (definicja ukończenia):

   ```bash
   make down && make up
   $K get ns shop loadgen aiops intruder monitoring -L pod-security.kubernetes.io/enforce,pod-security.kubernetes.io/warn,pod-security.kubernetes.io/audit | tee reports/t13-etykiety.txt
   printf '%s\n' 'apiVersion: v1' 'kind: Pod' 'metadata:' '  name: t13-privileged' '  namespace: shop' 'spec:' '  containers:' '    - name: probe' '      image: ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev' '      securityContext:' '        privileged: true' \
     | $K apply --dry-run=server -f - 2>&1 | tee reports/t13-dry-run.txt
   $K -n shop get pod t13-privileged
   $PYTEST tests/security -v | tee reports/t13-pytest.txt
   $K get pods -A -l app.kubernetes.io/part-of=secure-k8s-aiops | tee reports/t13-pody.txt
   sleep 120
   $K get pods -A -l app.kubernetes.io/part-of=secure-k8s-aiops | tee reports/t13-pody-2min.txt
   ```

   - `make up` → kod 0;
   - etykiety jak w kroku 3;
   - sprawdzenie z issue (dry-run poda z `privileged: true` w shop) → `Error from server (Forbidden): ... pods "t13-privileged" is forbidden: violates PodSecurity "restricted:latest": privileged (container "probe" must not set securityContext.privileged=true), ...`; `get pod` → `Error from server (NotFound)`;
   - pytest → `92 passed` (bez internetu `89 passed, 3 skipped`);
   - 4 pody `1/1 Running`: frontend i orders w shop, fault-runner w loadgen, intruder w intruder;
   - kolumna `RESTARTS` w `reports/t13-pody-2min.txt` jest taka sama jak w `reports/t13-pody.txt`.
6. `git status --short` → pusty, bo `reports/` jest w `.gitignore`.

## Po dostarczeniu (GitHub)

Wykonuje główny agent po Verification i po code review bez CRITICAL/HIGH, na klastrze z kroku 5. W jednej sesji bash ustaw `set -o pipefail`, `R=l3x1cn/secure-k8s-aiops` i `B=$(git branch --show-current)`.

Jeśli po Verification doszedł commit, np. poprawki z code review, przed krokiem 1:
- powtórz na HEAD kroki 1 i 5 Verification;
- gdy commit zmienia `tests/security/test_pod_security.py` albo `deploy/`, powtórz też kroki 2–4. Przed krokiem 2 wykonaj `git switch main && make deploy && git switch t13-pod-security`, żeby klaster miał manifesty z `main`.

Commit w dowodzie (`git rev-parse --short HEAD`) musi być tym, który przeszedł Verification.

1. Gałąź i PR:

```bash
git push -u origin "$B"
gh pr create --repo "$R" --base main --head "$B" --title "T13 · Pod Security Admission i securityContext" \
  --body "Closes #13 — opis i dowód kryteriów akceptacji po weryfikacji."
PR=$(gh pr view "$B" --repo "$R" --json number --jq .number)
sleep 30
gh pr checks "$PR" --repo "$R" --watch --interval 15
gh pr checks "$PR" --repo "$R" --required --json name,bucket --jq '.[] | "\(.name) \(.bucket)"' | sort
```

   - Gdy `gh pr checks` wypisze `no checks reported`, czekaj 30 s i powtórz, najwyżej 5 razy.
   - Oczekiwane wymagane kontrole: `images pass`, `lint pass`, `manifests pass`, `secrets pass`, `unit pass`.
2. Dowód w #13:

````bash
noansi() { sed -r 's/\x1B\[[0-9;]*[A-Za-z]//g' "$1"; }
{
  echo "## Dowód kryteriów akceptacji T13"; echo
  echo "Gałąź \`$B\`, commit \`$(git rev-parse --short HEAD)\`; kind 0.33.0 (Kubernetes 1.36.4), kubectl 1.37.1, klaster z \`make down && make up\`."; echo
  echo "### 1. Uprzywilejowany pod w shop jest odrzucany (\`kubectl apply --dry-run=server\`)"; echo
  echo '```text'; cat reports/t13-dry-run.txt; echo '```'; echo
  echo "### 2. Testy przechodzą, a własne pody działają z nowym securityContext"; echo
  echo '```text'; noansi reports/t13-pytest.txt | grep -E 'test_pod_security|passed|failed'; echo; cat reports/t13-pody.txt; echo; cat reports/t13-etykiety.txt; echo '```'; echo
  echo "Ten sam test przed \`make deploy\` T13 i po mutacjach (\`enforce=baseline\` w shop i \`privileged\` w intruder; \`readOnlyRootFilesystem: false\` w fault-runner):"; echo
  echo '```text'; for f in przed mutacja-psa mutacja-rofs; do echo "== $f"; noansi "reports/t13-$f.txt" | grep -E '^FAILED|passed|failed'; done; echo '```'; echo
  echo "### 3. \`trivy config deploy/\`: 0 HIGH, 0 CRITICAL"; echo
  echo '```text'; noansi reports/t13-trivy.txt | sed -n '/Report Summary/,/Legend/p'; echo '```'
} > reports/t13-dowod.md
URL=$(gh issue comment 13 --repo "$R" --body-file reports/t13-dowod.md)
echo "$URL"
````

3. Opis PR i prośba o review:
   - zapisz `reports/t13-pr.md` z treścią poniżej i wstaw `$URL` z kroku 2;
   - `gh pr edit "$PR" --repo "$R" --body-file reports/t13-pr.md --add-reviewer DreadGoblin`;
   - nie scalaj: PR wymaga zatwierdzenia drugiej osoby. Checkboxów w issue nie zaznaczaj.

```markdown
Closes #13

- `deploy/base/namespaces.yaml`: etykiety PSA `enforce`, `warn` i `audit` = restricted w shop, loadgen, aiops i intruder. monitoring ma privileged we wszystkich trzech trybach i komentarz z uzasadnieniem (node-exporter i Alloy potrzebują dostępu do hosta).
- `deploy/base/{fault-runner,intruder}/deployment.yaml`: `/tmp` z `emptyDir` (`sizeLimit: 16Mi`), jak frontend i orders. Pozostałe pola securityContext były już w manifestach (T05, T08, T12).
- `tests/security/test_pod_security.py` (marker `security`), 5 testów:
  - `kubectl apply --dry-run=server` poda z `privileged: true` w shop, loadgen, aiops i intruder → `violates PodSecurity "restricted:latest"`;
  - każdy kontener działającego własnego poda ma:
    - `runAsNonRoot`, `readOnlyRootFilesystem` i `/tmp` z emptyDir;
    - `allowPrivilegeEscalation: false`, `drop: [ALL]` bez `add`, seccomp `RuntimeDefault`;
    - UID 10001 dla obrazów projektu.
- Kontrakt: `docs/architektura.md`, sekcja „Namespace'y i Pod Security”; README: zakres testów bezpieczeństwa.

Odstępstwo od zakresu issue: intruder (`curlimages/curl`) działa jako 10001, nie jako domyślny `curl_user` (uid 100). curl działa z dowolnym UID, a 10001 zostaje jednolity dla wszystkich podów (Trivy KSV-0020, KSV-0021). Reguła dla obrazów zewnętrznych jest w architekturze.

Etykiet `warn` i `audit` test nie sprawdza, bo w kind nie mają obserwowalnego skutku:
- bez etykiety `warn` PSA bierze poziom z `enforce`;
- `audit` działa tylko z logiem audytu, którego kind nie ma.

Etykiety pokazuje `kubectl get ns -L …` w dowodzie.

Kryteria akceptacji, dowód: <URL>
- [x] Test przechodzi, a wszystkie własne pody działają z nowym securityContext:
  - `92 passed` w `tests/security` na klastrze z `make down && make up`;
  - przed `make deploy` T13 `1 failed, 4 passed` (brak `/tmp` w fault-runner i intruder);
  - mutacja `enforce=baseline` w shop i `privileged` w intruder → 2 failed;
  - mutacja `readOnlyRootFilesystem: false` w fault-runner (PSA ją przepuszcza) → 1 failed.
- [x] `trivy config --severity HIGH,CRITICAL --exit-code 1 deploy/` → kod 0. Pozostałe uwagi to KSV-0013, KSV-0110 i KSV-0125 (MEDIUM i LOW), jak przed T13.

@DreadGoblin: proszę o review.
```

4. Komentarze w zadaniach zależnych, każdy przez `gh issue comment <N> --repo "$R" --body "<treść>"`:
   - #18: „T13: loadgen ma PSA restricted (`enforce`, `warn`, `audit`). Kontener locust potrzebuje securityContext z kontraktu (`docs/architektura.md`, sekcja „Namespace'y i Pod Security”, wzór `deploy/base/frontend/deployment.yaml`): `runAsNonRoot`, `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `/tmp` z `emptyDir` (`sizeLimit: 16Mi`) jako jedyny zapisywalny katalog. UID: 10001, jeśli `locustio/locust` z nim działa, inaczej domyślny UID obrazu wpisany liczbą (kubelet nie uruchomi kontenera z `runAsNonRoot`, gdy obraz podaje użytkownika nazwą). `tests/security/test_pod_security.py` sprawdza każdy pod z etykietą `app.kubernetes.io/part-of=secure-k8s-aiops`.”
   - #24: „T13: aiops ma PSA restricted (`enforce`, `warn`, `audit`). Obraz anomaly-detector: `USER 10001:10001` w Dockerfile. Deployment z securityContext jak `deploy/base/frontend/deployment.yaml`: `runAsUser`/`runAsGroup` 10001, `readOnlyRootFilesystem: true`, `/tmp` z `emptyDir` (`sizeLimit: 16Mi`) jako jedyny zapisywalny katalog. `tests/security/test_pod_security.py` sprawdza każdy pod z etykietą `app.kubernetes.io/part-of=secure-k8s-aiops`, a dla obrazów `ghcr.io/l3x1cn/secure-k8s-aiops/*` także UID 10001.”

## Assumptions & contingencies

Założenia (właściciel może je zmienić):
- intruder zostaje na UID 10001; decyzja właściciela z 2026-11-10, opisana w PR jako odstępstwo od tekstu issue.
- `test_privileged_pod_is_rejected` obejmuje cztery namespace'y restricted, nie tylko shop z issue. `test_own_containers_are_hardened` wynika z decyzji właściciela.
- monitoring ma privileged także w `warn` i `audit`. Alternatywa: `warn`/`audit` = baseline, ale wtedy każde `make up` od T16 wypisuje ostrzeżenia dla node-exportera.
- `/tmp` z `emptyDir` dostaje każdy własny workload, także intruder, choć curl go nie potrzebuje (dosłowny zakres issue, jeden wzór).
- Etykiety bez `*-version` (domyślnie `latest`).
- Etykiet `warn` i `audit` nie pilnuje test: ich usunięcie nie zmienia wyniku `tests/security`. Alternatywa: deklaratywny test etykiet w każdym z 5 namespace'ów, jak `test_namespace_has_default_deny` w `tests/security/test_network_policies.py`; daje 5 testów więcej (`97 passed`).

Plan awaryjny:
- **Krok 2 daje `5 passed`:** klaster ma już manifesty T13, mimo `make deploy` z `main` w warunku wstępnym. Potwierdza to `$K -n loadgen get deploy fault-runner -o jsonpath='{.spec.template.spec.volumes[*].name}'` z `tmp` w wyniku. Wykonaj `git switch main && make deploy && git switch t13-pod-security` i powtórz krok 2. Gdy wynik się nie zmienia, pomiń krok 2, bo wykrywanie dowodzą mutacje z kroku 4. Wtedy usuń `przed` z pętli `for f in przed mutacja-psa mutacja-rofs` w skrypcie dowodu, a z `reports/t13-pr.md` punkt „przed `make deploy` T13 `1 failed, 4 passed`”.
- **`make deploy` przekracza timeout albo fault-runner lub intruder nie jest `Running` po dodaniu `/tmp`:** `$K -n <ns> describe pod -l app.kubernetes.io/name=<nazwa>` i `$K -n <ns> get events --sort-by=.lastTimestamp`. Nie usuwaj `readOnlyRootFilesystem` ani wolumenu; zatrzymaj się i zgłoś wynik.
- **`make deploy` wypisuje `Warning: would violate PodSecurity`:** szablon łamie restricted (prototyp go nie dawał). Zatrzymaj się i zgłoś komunikat.
- **`test_privileged_pod_is_rejected` pada z innym błędem, np. `namespaces "aiops" not found`:** `make namespaces`, potem powtórz krok.
- **`make namespaces` po mutacji nie przywraca `restricted`:** `$K label ns shop pod-security.kubernetes.io/enforce=restricted --overwrite` i to samo dla intruder, potem `$K get ns -L pod-security.kubernetes.io/enforce`.
- **Trivy zgłasza HIGH albo CRITICAL:** popraw według komunikatu bez osłabiania securityContext. KSV-0013, KSV-0110 i KSV-0125 to znane uwagi MEDIUM i LOW.
- **`make up` pada na zajętym porcie (`address already in use`):** zwolnij port 8080, 3000 albo 8025 na `127.0.0.1` i powtórz.
