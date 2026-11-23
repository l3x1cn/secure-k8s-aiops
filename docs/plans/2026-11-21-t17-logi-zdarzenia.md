# T17 · Logi i zdarzenia: Loki + Grafana Alloy (issue #17)

## Context

Issue #17 (R1 Platforma, Sprint 2, zależy od T16 — scalone): logi kontenerów i zdarzenia Kubernetes mają być w Grafanie. Zakres: Loki z chartu `grafana-community/helm-charts` (SingleBinary, filesystem, retencja 72 h, bez gatewaya, usługa :3100); Grafana Alloy z chartu `grafana/alloy` jako DaemonSet (logi podów z `/var/log/pods` dla shop, loadgen, aiops i intruder, etykiety namespace/pod/container, JSON z polem `level`, `loki.source.kubernetes_events` dla tych samych namespace'ów z `log_format = "json"`); źródło Loki w Grafanie z wartości kube-prometheus-stack. Kryteria akceptacji:
1. po `fault-runner fault errors` zapytanie `{namespace="shop", container="orders"} | json | level="ERROR"` zwraca logi;
2. `{job="loki.source.kubernetes_events"}` zawiera zdarzenia, np. `BackOff` po `fault-runner fault crash`.

Komentarze w #17: T11 — nowe CRD albo grupę API z chartu dopisać do `sre-readonly` (`test_sre_reads_every_listable_resource_except_secrets`); T16 — źródło Loki w `grafana.additionalDataSources` w `deploy/observability/values/kube-prometheus-stack.yaml`, charty Loki i Alloy jako kolejne kroki `make observability`, values w `deploy/observability/values/`. Ryzyko R2 w `docs/bezpieczenstwo.md:111` ma w kolumnie „Kiedy wracamy” wpis „T17: przegląd wartości chartu Alloy”, więc utwardzenie wartości Alloy należy do T17.

Stan docelowy: `make observability` (krok `make up`) instaluje po kube-prometheus-stack release'y `loki` i `alloy` z rejestrów OCI, przypięte wersją i digestem; Grafana ma źródło `Loki` (uid `loki`); nowy `tests/observability/test_logs.py` dowodzi obu kryteriów i źródła w Grafanie; `test_rbac.py` pilnuje uprawnień konta Alloy; README, `docs/architektura.md` i `docs/bezpieczenstwo.md` opisują kontrakt logów i ryzyka.

### Ustalone fakty (sprawdzone 2026-11-21)

- **Repozytorium:** `main` = `origin/main` = `0056ffb` (T26), drzewo czyste. T16, T18, T19, T26 scalone. Numery linii w planie pochodzą z `0056ffb`.
- **Klaster `kind-secure-k8s-aiops` działa** (7 h): control-plane + 2 workery, Kubernetes v1.36.4, containerd 2.3.4. Release'y: `cilium`, `prometheus-operator-crds`, `kube-prometheus-stack` 92.17.1; Loki i Alloy nie istnieją. Pody shop, loadgen i intruder są tylko na workerach (control-plane ma taint). StorageClass `standard` (local-path) jest domyślna. Zużycie pamięci węzłów ok. 4,5 GiB.
- **Grafana 13.3.0** ma źródła `Prometheus` (uid `prometheus`) i `Alertmanager` (uid `alertmanager`); `GET /api/datasources/uid/prometheus/health` z kontem z Secretu `grafana-admin` zwraca 200 i `"status": "OK"`. Kontenery poda: `grafana-sc-dashboard`, `grafana-sc-datasources`, `grafana` (sidecar przeładowuje źródła z ConfigMapy `kube-prometheus-stack-grafana-datasource`, w której kube-prometheus-stack renderuje `grafana.additionalDataSources`).
- **Pliki logów na węźle** (`docker exec secure-k8s-aiops-worker2 stat …`): `/var/log` 0755, `/var/log/pods` **0750 root:root**, katalogi podów i kontenerów 0755, pliki `<n>.log` **0640 root:root**. Linie w formacie CRI: `2026-11-21T11:38:42.306406049Z stdout F {"ts": …, "level": "INFO", "service": "orders", …}`.
- **Chart Loki** jest w OCI `oci://ghcr.io/grafana-community/helm-charts/loki` (README repozytorium: OCI preferowane). Wydania z `index.yaml`: 21.2.3 (Loki 3.7.10) 2026-11-13, 21.3.0 2026-11-16, …, 21.4.3 2026-11-21 (Loki 3.7.10). Wybór: **21.2.3**, najnowsze wydanie starsze niż 7 dni (cooldown jak w Dependabot i przy pinie kube-prometheus-stack w T16, PR #55). Digest manifestu 21.2.3: `sha256:bd02e2e55cdc0f0ac0cfbb2e01a01b7eba5316787a8ec38a35f315bbd405eed6`. Różnice 21.2.3 → 21.4.3 dotyczą tylko komponentów Loki 4.0 (dataobj, logline) i tagu obrazu nginx gatewaya.
- **Domyślne wartości chartu Loki 21.2.3:** `deploymentMode: Monolithic` (nowa nazwa trybu SingleBinary; `SingleBinary` jest oznaczony jako przestarzały), `singleBinary.replicas: 0`, `backend|read|write.replicas: 3`, włączone `gateway`, `chunksCache` (8192 MB), `resultsCache` (1024 MB), `memcached`, `lokiCanary`, `test`, `sidecar.rules`; `loki.auth_enabled: true`, `commonConfig.replication_factor: 3`, `storage.type: s3`, `schemaConfig: {}`. `templates/validate.yaml`: z systemem plików najwyżej 1 replika Monolithic; repliki Monolithic obok replik backend/read/write to błąd; pusty `schemaConfig` to błąd. Sidecar reguł daje kontu `loki` ClusterRole z `get, watch, list` na `configmaps` i `secrets` w całym klastrze (`templates/backend/clusterrole.yaml`); bez sidecara ta rola ma `rules: []`. Usługa Monolithic to `loki` (porty `http-metrics` 3100, `grpc` 9095, `grpclb` 9096), pod `loki-0` ma etykiety `app.kubernetes.io/name: loki`, `app.kubernetes.io/component: single-binary`; PVC `storage-loki-0`. Pod i kontener mają domyślnie UID 10001, `runAsNonRoot`, `readOnlyRootFilesystem`, `drop: [ALL]`, `RuntimeDefault`. Wartości z Task 1 scalone z domyślnymi przechodzą `values.schema.json` chartu (0 błędów, jsonschema draft-07).
- **Chart Alloy** jest w OCI `oci://ghcr.io/grafana/helm-charts/alloy` (workflow `release.yaml` w grafana/helm-charts robi `helm push` do `ghcr.io/grafana/helm-charts`); jedyny tag OCI to **1.16.0** (2026-11-13, Alloy v1.22.0), warstwa z chartem ma ten sam digest co `alloy-1.16.0.tgz` z klasycznego repozytorium. Digest manifestu: `sha256:b55a879497d59b66b65c9147d1e4fe3d25f93e18aff046bdf014fbcf8871ea87`.
- **Domyślne wartości chartu Alloy 1.16.0:** `crds.create: true` (CRD `podlogs.monitoring.grafana.com`), ClusterRole z m.in. `get, list, watch` na `configmaps` i `secrets` w całym klastrze, `nodes`, `nodes/proxy`… (`rbac.rules`, `rbac.clusterRules`); `rbac.namespaces` zamienia ją na Role i RoleBinding w podanych namespace'ach z `rbac.rules`. `alloy.securityContext: {}`, `enableReporting: true`, `mounts.varlog` montuje hostPath `/var/log` z `readOnly: true`, `storagePath: /tmp/alloy`, `clustering.enabled` dodaje usługę `alloy-cluster` i `--cluster.join-addresses=alloy-cluster`. Kontener ma env `HOSTNAME` = `spec.nodeName`. `alloy.configMap.content` przechodzi przez `tpl` Helma. Obraz `docker.io/grafana/alloy:v1.22.0` działa domyślnie jako root (Dockerfile tworzy użytkownika `alloy` UID 473, ale go nie ustawia).
- **Alloy v1.22.0 (źródła i dokumentacja):** wszystkie użyte komponenty mają stabilność GA. `loki.source.file` ma blok `file_match` (glob w `__path__`, zalecany zamiast `local.file_match`) i dodaje etykietę `filename`. `stage.cri` ustawia etykietę `stream`. `loki.source.kubernetes_events` nadaje etykiety `namespace` (obiekt zdarzenia), `job` (`loki.source.kubernetes_events`) i `instance` (ID komponentu, takie samo w każdej instancji); linia JSON ma pola `name`, `kind`, `action`, `objectAPIversion`, `objectRV`, `eventRV`, `reportinginstance`, `reportingcontroller`, `sourcecomponent`, `sourcehost`, `reason`, `type`, `count`, `msg`; czas wpisu to `series.lastObservedTime`, `lastTimestamp` albo `eventTime`. Blok `clustering { enabled = true }` dzieli listę namespace'ów między instancje klastra Alloy (consistent hashing); bez niego każda instancja DaemonSetu czyta wszystkie.
- **Helm 4.3.1** usuwa wyłączone podcharty przed instalacją CRD (`pkg/action/install.go:324` przed `:331`), więc `crds.create: false` nie instaluje CRD PodLogs, a CRD wyłączonego podchartu `rollout_operator` w chartcie Loki nie powstają.
- **Kubelet 1.36:** początkowy back-off crashy 10 s (`ReduceDefaultCrashLoopBackOffDecay` alpha, wyłączone), wpis wygasa po 600 s (`pkg/kubelet/kubelet.go`). `doBackOff` (`kuberuntime_manager.go`): pierwszy crash restartuje od razu bez zdarzenia; kolejny w ciągu 10 min daje zdarzenie Warning `BackOff` z treścią `Back-off restarting failed container orders in pod …`. Jedno `fault-runner fault crash` nie wystarcza do `BackOff`.
- **Aplikacje:** awaria `errors` rzuca `HTTPException(500)` na trasach `/orders` (`services/orders/src/orders/faults.py:111-121`), a middleware loguje żądanie z `"level": "ERROR"`, `"status": 500`, `"route": "/orders"` (`libs/observability/src/observability/__init__.py:112-130`); `POST /order` frontendu woła `POST /orders`. Endpoint crash loguje ERROR `fault crash: exiting process` (bez `status`) i kończy proces kodem 1.
- **Bramki CI:** `make trivy-config` skanuje tylko manifesty Kubernetes z `deploy/` (`reports/trivy/config.json`: pliki z `values/` nie są celami), `make manifests` waliduje tylko wynik `kustomize build`. Pliki values nie mogą zawierać napisu `trivy:ignore` (`scripts/trivy.sh:74`).
- **Testy:** `tests/observability` ma 12 testów (`test_metrics.py` 11, `test_traffic.py` 1), `make test-security` — 104 (plan T26), `make unit` — 96. Wzorzec: `kubectl()` i fixture `cluster` z `tests/observability/test_metrics.py:45-98`, zapytania przez proxy API serwera (`kubectl get --raw`), `--timeout=45s` mieści się w 60-sekundowym limicie `subprocess.run` (plan T26). Szkic `test_logs.py` i łata `test_rbac.py` z planu przechodzą `ruff format` (bez zmian) i `ruff check` z konfiguracją repo.
- **Konwencje:** gałąź `txx-krotki-opis`, PR z `Closes #N`; plan trafia do `docs/plans/<data>-<slug>.md` commitem `docs: add delivery plan <slug>`; `reports/` jest w `.gitignore`.

## Warunek wstępny (główny agent, przed startem delivery)

W korzeniu repozytorium:

```bash
git status --short   # pusto
git switch main && git pull --ff-only && git switch -c t17-logi-zdarzenia
mise exec -- kind get clusters                                   # secure-k8s-aiops
mise exec -- kubectl --context kind-secure-k8s-aiops get --raw /readyz   # ok
```

- Brak klastra albo `readyz` inne niż `ok` → `make up`.
- Potem `make deploy` (manifesty klastra jak na gałęzi).
- Taski 1–2 potrzebują sieci: `ghcr.io` (charty), `docker.io` (obrazy `grafana/loki`, `grafana/alloy`), `quay.io` (`prometheus-config-reloader`).
- Plan trafia do `docs/plans/2026-11-21-t17-logi-zdarzenia.md` commitem `docs: add delivery plan t17-logi-zdarzenia`.
- Jeśli `main` ma nowsze commity w plikach z tego planu, przeczytaj je ponownie i przenieś zmiany na nowe numery linii; edycje są opisane treścią.

## Approach

Kolejność 1 → 2 → 3 → 4. Taski 1, 2 i 4 to stos „pozostałe” (Makefile, konfiguracja Helm, Markdown), Task 3 to Python. Task 2 wymaga działającego Lokiego z Task 1 (Alloy wysyła do `loki.monitoring.svc:3100`), Task 3 wymaga obu chartów w klastrze, Task 4 opisuje nazwy z Tasków 1–3.

Decyzje wspólne:
- **Charty z OCI, jak dotąd.** Oba charty są w rejestrach OCI, więc obowiązuje istniejąca reguła pinów: `*_VERSION` i `*_CHART_DIGEST` w `platform/versions.env`, instalacja `<chart>@<digest> --version <wersja>`. Nie używamy klasycznych repozytoriów Helm (`helm repo add`).
- **Wersje:** Loki 21.2.3, Alloy 1.16.0 (fakty wyżej).
- **Loki:** release `loki` w monitoring, `deploymentMode: Monolithic`, 1 replika, filesystem na PVC 5 Gi, retencja 72 h przez compactor, `auth_enabled: false`. Wyłączone: gateway, cache'e memcached i `memcached`, canary, helm test, sidecar reguł (inaczej ClusterRole z odczytem secrets), statystyki użycia (`analytics.reporting_enabled: false`). Brak NetworkPolicy dla Lokiego: monitoring nie ma polityk (ryzyko R1), Task 4 dopisuje do R1 dostęp do Lokiego bez uwierzytelnienia.
- **Alloy:** release `alloy`, DaemonSet bez tolerancji (2 pody na workerach; na control-plane nie ma podów z czterech namespace'ów). Logi: `discovery.kubernetes` (pody z czterech namespace'ów z węzła instancji) → `discovery.relabel` (`namespace`, `pod`, `container`, `__path__` według dokumentacji Alloy) → `loki.source.file` z `file_match` → `loki.process` (`stage.cri`, `stage.json` + `stage.labels` dla `level`, `stage.label_drop` dla `filename`). Zdarzenia: `loki.source.kubernetes_events` z `clustering`, a instancje tworzą klaster Alloy, więc każdy namespace czyta jedna instancja. `level` jest etykietą strumienia: 4 wartości, a zapytanie z kryterium działa tak samo (LogQL nazywa wtedy pole z `| json` `level_extracted`, a filtr `level="ERROR"` trafia w etykietę).
- **Utwardzenie Alloy (R2):** `crds.create: false`; `rbac.namespaces` z Role tylko `get, list, watch` na `pods` i `events`; UID 473 z grupą 0 (wystarcza do `0750`/`0640 root:root`), `runAsNonRoot`, bez eskalacji, `drop: [ALL]`, `readOnlyRootFilesystem` z `emptyDir` na `/tmp` (`storagePath` `/tmp/alloy` przeżywa restart kontenera, więc pliki nie są czytane od nowa); `enableReporting: false`.
- **Testy:** `tests/observability/test_logs.py` (marker `observability`, 3 testy) i 12 wierszy `sa:monitoring/alloy` w `MATRIX` `tests/security/test_rbac.py`. Test zdarzeń robi dwa crashe orders, bo `BackOff` powstaje dopiero przy drugim (kubelet); skutki uboczne jak S5 (e-mail PodRestarts) opisuje Task 4.
- Bez zmian: CI, `mise.toml`, `deploy/base`, `deploy/overlays`, `scripts/`, `sre-readonly` (brak nowych CRD i grup API).

### Task 1: Loki w make observability i źródło Loki w Grafanie
**Commit:** feat(observability): Loki w make observability i źródło Loki w Grafanie (T17)

**Files:**
- Modify: `platform/versions.env`
- Modify: `Makefile`
- Modify: `deploy/observability/values/kube-prometheus-stack.yaml`
- Create: `deploy/observability/values/loki.yaml`

1. `platform/versions.env`: po linii 14 (`KUBE_PROMETHEUS_STACK_CHART_DIGEST=…`) dopisz:

```
# Loki (T17): chart z grafana-community/helm-charts (od 16.03.2026 tam jest chart OSS), OCI ghcr.io/grafana-community/helm-charts.
# 21.2.3 (Loki 3.7.10) to najnowsze wydanie starsze niż 7 dni w dniu wyboru (21.11.2026; cooldown jak w Dependabot i T16).
# 21.3–21.4 zmieniają tylko komponenty Loki 4.0 i obraz gatewaya, których nie używamy.
LOKI_VERSION=21.2.3
LOKI_CHART_DIGEST=sha256:bd02e2e55cdc0f0ac0cfbb2e01a01b7eba5316787a8ec38a35f315bbd405eed6
```

2. `Makefile`:
   - po linii 17 (`KUBE_PROMETHEUS_STACK_CHART := …`) wstaw `LOKI_CHART := oci://ghcr.io/grafana-community/helm-charts/loki`;
   - komentarz nad celem `observability` (linie 106–109) zastąp:

```make
# kube-prometheus-stack w monitoring (T16): Prometheus, Alertmanager, Grafana (NodePort 30300), kube-state-metrics, node-exporter.
# Potem Loki (T17): tryb SingleBinary, usługa loki.monitoring.svc:3100; źródło Loki w Grafanie dodają wartości kube-prometheus-stack.
# Wersje i digesty z platform/versions.env, wartości w deploy/observability/values/; CRD instaluje make cluster.
# Grafana czyta hasło admina z Secretu grafana-admin, więc sekrety muszą istnieć przed instalacją.
# ServiceMonitory aplikacji, reguły nagrywające i alertów oraz Mailpit stosuje make deploy (deploy/base, deploy/observability).
```

   - po linii 114 (`--values deploy/observability/values/kube-prometheus-stack.yaml --wait --timeout 10m`) dopisz polecenie (wcięcie tabulatorem, kontynuacja dwoma tabulatorami, jak wyżej):

```make
	helm upgrade --install loki $(LOKI_CHART)@$(LOKI_CHART_DIGEST) \
		--version $(LOKI_VERSION) \
		--kube-context $(KUBE_CONTEXT) --namespace monitoring \
		--values deploy/observability/values/loki.yaml --wait --timeout 10m
```

3. Utwórz `deploy/observability/values/loki.yaml`:

```yaml
# Wartości chartu Loki (T17) z grafana-community/helm-charts. Wersja i digest: LOKI_* w platform/versions.env;
# instalacja: make observability (krok make up), release loki w namespace monitoring.
# Tryb SingleBinary (w chartcie deploymentMode: Monolithic, dawniej SingleBinary): jeden pod loki-0 (StatefulSet
# loki) z danymi w systemie plików na PVC. Usługa loki.monitoring.svc:3100 bez gatewaya: Alloy wysyła logi
# (/loki/api/v1/push), czytają Grafana i anomaly-detector (T24).
deploymentMode: Monolithic

loki:
  # Jeden tenant bez nagłówka X-Scope-OrgID; brak uwierzytelnienia opisuje ryzyko R1 w docs/bezpieczenstwo.md.
  auth_enabled: false
  commonConfig:
    replication_factor: 1
  storage:
    type: filesystem
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: index_
          # Retencja wymaga indeksu dziennego.
          period: 24h
  # Retencja 72 h: starsze dane usuwa compactor. Helm scala tę mapę z domyślną mapą chartu.
  limits_config:
    retention_period: 72h
  compactor:
    retention_enabled: true
    delete_request_store: filesystem
  # Bez anonimowych statystyk użycia wysyłanych do Grafana Labs.
  analytics:
    reporting_enabled: false

singleBinary:
  # Domyślnie 0; z systemem plików chart dopuszcza najwyżej 1.
  replicas: 1
  # StorageClass standard z kind (local-path), jak PVC Prometheusa.
  persistence:
    size: 5Gi
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      memory: 1Gi

# Pody trybu SimpleScalable (domyślnie po 3 repliki); walidacja chartu wymaga zera obok trybu Monolithic.
backend:
  replicas: 0
read:
  replicas: 0
write:
  replicas: 0

# Bez gatewaya nginx: klienci łączą się z usługą loki na :3100.
gateway:
  enabled: false
# memcached (domyślnie 8 GB pamięci na chunki i 1 GB na wyniki) przy jednym podzie jest zbędny;
# memcached.enabled: false usuwa też konto loki-memcached.
chunksCache:
  enabled: false
resultsCache:
  enabled: false
memcached:
  enabled: false
# Canary (DaemonSet z próbnymi logami) i helm test, który go wymaga.
lokiCanary:
  enabled: false
test:
  enabled: false
# Sidecar reguł czyta ConfigMapy i Secrety: chart dałby kontu loki ClusterRole z odczytem secrets
# w całym klastrze. Reguł Lokiego nie używamy (alerty są w Prometheusie).
sidecar:
  rules:
    enabled: false
```

4. `deploy/observability/values/kube-prometheus-stack.yaml`: w bloku `grafana:` po linii 77 (`    nodePort: 30300`), przed `  resources:`, wstaw (wcięcie dwie spacje, jak `service:`):

```yaml
  # Źródło Loki (T17) obok Prometheusa i Alertmanagera z chartu; uid loki dla dashboardów (T22).
  additionalDataSources:
    - name: Loki
      type: loki
      uid: loki
      url: http://loki.monitoring.svc:3100
      access: proxy
```

5. Sprawdzenie (skrót `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`, `L=/api/v1/namespaces/monitoring/services/loki:3100/proxy`):

```bash
mkdir -p reports
mise exec -- helm template loki oci://ghcr.io/grafana-community/helm-charts/loki@sha256:bd02e2e55cdc0f0ac0cfbb2e01a01b7eba5316787a8ec38a35f315bbd405eed6 \
  --version 21.2.3 --namespace monitoring --values deploy/observability/values/loki.yaml > reports/t17-loki.yaml
mise exec -- yq -N '.kind + "/" + .metadata.name' reports/t17-loki.yaml | sort
mise exec -- yq -o json -I0 'select(.kind == "ClusterRole") | .rules' reports/t17-loki.yaml
mise exec -- yq 'select(.kind == "ConfigMap" and .metadata.name == "loki") | .data["config.yaml"]' reports/t17-loki.yaml \
  | mise exec -- yq -o json -I0 '[.auth_enabled, .limits_config.retention_period, .compactor.retention_enabled, .common.replication_factor, .schema_config.configs[0].object_store]'
make observability
$K -n monitoring get pods -l app.kubernetes.io/name=loki
$K -n monitoring get pvc storage-loki-0
$K get --raw "$L/ready"
curl -s -H "Authorization: Basic $(printf 'admin:%s' "$(make grafana-password)" | base64 -w0)" http://localhost:3000/api/datasources/uid/loki/health
```

   - lista obiektów to dokładnie: `ClusterRole/loki-clusterrole`, `ClusterRoleBinding/loki-clusterrolebinding`, `ConfigMap/loki`, `ConfigMap/loki-runtime`, `Service/loki`, `Service/loki-headless`, `Service/loki-memberlist`, `ServiceAccount/loki`, `StatefulSet/loki`;
   - reguły ClusterRole: `[]`;
   - konfiguracja: `[false,"72h",true,1,"filesystem"]`;
   - `make observability` → kod 0; pod `loki-0` `1/1 Running`; PVC `Bound`, `5Gi`, `standard`; `ready` → `ready`;
   - health → `"status":"OK"`.

### Task 2: Grafana Alloy: logi podów i zdarzenia Kubernetes
**Commit:** feat(observability): Grafana Alloy zbiera logi podów i zdarzenia Kubernetes do Lokiego (T17)

**Files:**
- Modify: `platform/versions.env`
- Modify: `Makefile`
- Create: `deploy/observability/values/alloy.yaml`

1. `platform/versions.env`: po `LOKI_CHART_DIGEST=…` z Task 1 dopisz:

```
# Grafana Alloy (T17): chart grafana/alloy, OCI ghcr.io/grafana/helm-charts (pierwsze wydanie w OCI: 1.16.0, Alloy v1.22.0).
ALLOY_VERSION=1.16.0
ALLOY_CHART_DIGEST=sha256:b55a879497d59b66b65c9147d1e4fe3d25f93e18aff046bdf014fbcf8871ea87
```

2. `Makefile`:
   - po `LOKI_CHART := …` z Task 1 wstaw `ALLOY_CHART := oci://ghcr.io/grafana/helm-charts/alloy`;
   - w komentarzu nad `observability` po linii `# Potem Loki (T17): …` wstaw:

```make
# Na końcu Grafana Alloy (T17, DaemonSet): logi podów i zdarzenia z shop, loadgen, aiops i intruder do Lokiego; Role w tych
# namespace'ach, więc namespace'y (zależność secrets → namespaces) muszą istnieć przed instalacją.
```

   - po poleceniu `helm upgrade --install loki …` z Task 1 dopisz:

```make
	helm upgrade --install alloy $(ALLOY_CHART)@$(ALLOY_CHART_DIGEST) \
		--version $(ALLOY_VERSION) \
		--kube-context $(KUBE_CONTEXT) --namespace monitoring \
		--values deploy/observability/values/alloy.yaml --wait --timeout 10m
```

3. Utwórz `deploy/observability/values/alloy.yaml`. Treść `content` to składnia Alloy (komentarze `//`), wcięta o 6 spacji; nie może zawierać `{{` (chart przepuszcza ją przez `tpl`):

```yaml
# Wartości chartu Grafana Alloy (T17). Wersja i digest: ALLOY_* w platform/versions.env;
# instalacja: make observability (krok make up), release alloy w namespace monitoring.
# DaemonSet (domyślny controller chartu) na workerach kind: każdy pod czyta pliki /var/log/pods podów
# ze swojego węzła, a zdarzenia Kubernetes czyta jedna instancja na namespace (clustering).
# Kontrakt etykiet: docs/architektura.md, sekcja „Kontrakt metryk i logów”; dostęp do hosta: ryzyko R2
# w docs/bezpieczenstwo.md.

# CRD PodLogs (monitoring.grafana.com) służy tylko loki.source.podlogs, którego nie używamy; nowe CRD
# trzeba by dopisać do sre-readonly (test_sre_reads_every_listable_resource_except_secrets).
crds:
  create: false

alloy:
  configMap:
    # Chart przepuszcza treść przez tpl Helma, więc nie może zawierać {{ }}.
    content: |
      // Logi podów z plików węzła (wzorzec z dokumentacji Alloy „Collect Kubernetes logs”):
      // discovery.kubernetes → __path__ z UID poda i nazwy kontenera → loki.source.file.
      discovery.kubernetes "pods" {
        role = "pod"

        namespaces {
          names = ["shop", "loadgen", "aiops", "intruder"]
        }

        // Tylko pody z węzła tej instancji DaemonSetu; chart ustawia HOSTNAME na spec.nodeName.
        selectors {
          role  = "pod"
          field = "spec.nodeName=" + coalesce(sys.env("HOSTNAME"), constants.hostname)
        }
      }

      discovery.relabel "pods" {
        targets = discovery.kubernetes.pods.targets

        rule {
          source_labels = ["__meta_kubernetes_namespace"]
          target_label  = "namespace"
        }

        rule {
          source_labels = ["__meta_kubernetes_pod_name"]
          target_label  = "pod"
        }

        rule {
          source_labels = ["__meta_kubernetes_pod_container_name"]
          target_label  = "container"
        }

        // /var/log/pods/<namespace>_<pod>_<uid>/<kontener>/<numer restartu>.log
        rule {
          source_labels = ["__meta_kubernetes_pod_uid", "__meta_kubernetes_pod_container_name"]
          separator     = "/"
          target_label  = "__path__"
          replacement   = "/var/log/pods/*$1/*.log"
        }
      }

      loki.source.file "pods" {
        targets    = discovery.relabel.pods.output
        forward_to = [loki.process.pods.receiver]

        // Glob z __path__; nowe pliki (np. po restarcie kontenera) co 10 s.
        file_match {
          enabled = true
        }
      }

      loki.process "pods" {
        forward_to = [loki.write.default.receiver]

        // Format CRI: czas wpisu, etykieta stream (stdout, stderr) i treść linii.
        stage.cri {}

        // Pole level linii JSON z kontraktu logów jako etykieta; linia spoza JSON zostaje bez level.
        stage.json {
          expressions = { level = "" }
        }

        stage.labels {
          values = { level = "" }
        }

        // loki.source.file dodaje etykietę filename; strumień wyznaczają namespace, pod i container.
        stage.label_drop {
          values = ["filename"]
        }
      }

      // Zdarzenia Kubernetes z tych samych namespace'ów jako linie JSON, job="loki.source.kubernetes_events".
      // Z clusteringiem każdy namespace czyta jedna instancja, więc zdarzenie trafia do Lokiego raz.
      loki.source.kubernetes_events "events" {
        namespaces = ["shop", "loadgen", "aiops", "intruder"]
        log_format = "json"
        forward_to = [loki.write.default.receiver]

        clustering {
          enabled = true
        }
      }

      loki.write "default" {
        endpoint {
          url = "http://loki.monitoring.svc:3100/loki/api/v1/push"
        }
      }
  # Instancje DaemonSetu tworzą klaster Alloy przez usługę alloy-cluster (port 12345).
  clustering:
    enabled: true
  # Bez anonimowych statystyk użycia wysyłanych do Grafana Labs (--disable-reporting).
  enableReporting: false
  mounts:
    # hostPath /var/log tylko do odczytu (readOnly w chartcie): logi podów w /var/log/pods.
    varlog: true
    # Jedyny zapisywalny katalog. Pozycje odczytu plików i zdarzeń są w storagePath /tmp/alloy (domyślna
    # wartość chartu), więc po restarcie kontenera Alloy nie czyta plików od początku.
    extra:
      - name: tmp
        mountPath: /tmp
  # Obraz domyślnie działa jako root. /var/log/pods ma 0750 root:root, a pliki logów 0640 root:root,
  # więc wystarcza grupa 0; 473 to użytkownik alloy z obrazu.
  securityContext:
    runAsNonRoot: true
    runAsUser: 473
    runAsGroup: 0
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop: [ALL]
    seccompProfile:
      type: RuntimeDefault
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      memory: 512Mi

controller:
  volumes:
    extra:
      - name: tmp
        emptyDir:
          sizeLimit: 64Mi

# Zamiast domyślnej ClusterRole chartu (m.in. odczyt secrets i configmaps w całym klastrze): Role i RoleBinding
# alloy w każdym namespace'ie z logami, tylko pody (discovery.kubernetes) i zdarzenia (loki.source.kubernetes_events).
rbac:
  namespaces: [shop, loadgen, aiops, intruder]
  rules:
    - apiGroups: [""]
      resources: [pods, events]
      verbs: [get, list, watch]
```

4. Sprawdzenie (`K` i `L` jak w Task 1):

```bash
mise exec -- helm template alloy oci://ghcr.io/grafana/helm-charts/alloy@sha256:b55a879497d59b66b65c9147d1e4fe3d25f93e18aff046bdf014fbcf8871ea87 \
  --version 1.16.0 --namespace monitoring --values deploy/observability/values/alloy.yaml > reports/t17-alloy.yaml
mise exec -- yq -N '.kind + "/" + (.metadata.namespace // "-") + "/" + .metadata.name' reports/t17-alloy.yaml | sort
mise exec -- yq 'select(.kind == "ConfigMap") | .data["config.alloy"]' reports/t17-alloy.yaml > reports/t17-config.alloy
docker run --rm -i docker.io/grafana/alloy:v1.22.0 fmt - < reports/t17-config.alloy > /dev/null && echo skladnia-ok
make observability
$K -n monitoring get daemonset alloy
$K -n monitoring get pods -l app.kubernetes.io/name=alloy -o wide
$K -n monitoring exec ds/alloy -c alloy -- id
$K get crd podlogs.monitoring.grafana.com
sleep 30
$K get --raw "$L/loki/api/v1/labels"
$K get --raw "$L/loki/api/v1/label/namespace/values"
$K get --raw "$L/loki/api/v1/label/level/values"
```

   - obiekty to dokładnie: `ConfigMap/monitoring/alloy`, `DaemonSet/monitoring/alloy`, `Role/<ns>/alloy` i `RoleBinding/<ns>/alloy` dla `aiops`, `intruder`, `loadgen`, `shop`, `Service/monitoring/alloy`, `Service/monitoring/alloy-cluster`, `ServiceAccount/monitoring/alloy` (13 obiektów, bez ClusterRole i CRD);
   - `skladnia-ok` (`alloy fmt` sprawdza tylko składnię; wyniku formatowania nie przenoś do values);
   - `make observability` → kod 0; DaemonSet `DESIRED 2`, `READY 2`, pody na `secure-k8s-aiops-worker` i `secure-k8s-aiops-worker2`, `RESTARTS 0`;
   - `id` → zaczyna się od `uid=473(alloy) gid=0(root)`;
   - CRD → `NotFound`;
   - etykiety zawierają `container`, `level`, `namespace`, `pod`, `stream` i nie zawierają `filename` (etykiety zdarzeń `job` i `instance` pojawiają się po pierwszym zdarzeniu w czterech namespace'ach; sprawdzają je Task 3 i krok 3 Verification);
   - wartości `namespace` to podzbiór `aiops`, `intruder`, `loadgen`, `shop` i zawierają `loadgen` oraz `shop`;
   - wartości `level` zawierają `INFO`.

### Task 3: Testy logów, zdarzeń, źródła Loki i uprawnień konta Alloy
**Commit:** test(observability): logi ERROR, zdarzenie BackOff i źródło Loki w Grafanie; uprawnienia konta Alloy (T17)

**Files:**
- Create: `tests/observability/test_logs.py`
- Test: `tests/security/test_rbac.py`

1. Utwórz `tests/observability/test_logs.py` z treścią poniżej (sformatowana ruffem 0.17.3; nie zmieniaj formatowania). Decyzje zawarte w treści:
   - wzorzec `kubectl()` i fixture `cluster` jak `tests/observability/test_metrics.py:45-98`; oczekiwanie na Lokiego, DaemonSet `alloy` i fault-runner;
   - Loki przez proxy API serwera (`services/loki:3100/proxy`), Grafana przez `localhost:3000` z kontem z Secretu `grafana-admin` (`kubectl get --raw` nie doda nagłówka uwierzytelnienia Grafany); wartości Secretu nie trafiają do komunikatów;
   - kolejność w pliku: najpierw test bez skutków ubocznych (Grafana), potem `errors`, na końcu crash;
   - `fault_runner()` ponawia do 5 razy co 2 s: po restarcie orders usługa dostaje endpoint chwilę po gotowości kontenera, a nieudane wywołanie nie dociera do orders, więc ponowienie jest bezpieczne;
   - awaria `errors` z `ratio=1` przez 30 s i własny ruch `spike --users 1 --seconds 15` (bez zależności od fazy sinusoidy Locusta); `fault-runner stop` w `finally`. Asercje: etykieta `pod` z Alloy, co najmniej jeden wpis to odpowiedź 500 na `/orders`, a selektor z etykietą `level="ERROR"` (bez `| json`) też zwraca wpisy, więc etykietę nadaje Alloy;
   - dwa crashe: drugi dopiero po restarcie i gotowości po pierwszym; w `finally` czekanie na tyle restartów, ile crashy faktycznie wysłano, żeby nie maskować pierwotnego błędu;
   - okno zapytań zaczyna się sekundę przed testem (znaczniki zdarzeń mają dokładność do sekundy); limit oczekiwania 120 s na wpisy i 180 s na restart orders (powtórzony przebieg w ciągu 10 min wydłuża back-off).

```python
# Logi i zdarzenia (T17) na działającym klastrze: Alloy wysyła do Lokiego logi podów
# z /var/log/pods i zdarzenia Kubernetes z shop, loadgen, aiops i intruder, a Grafana ma
# źródło Loki (docs/architektura.md, sekcja „Kontrakt metryk i logów”; wartości chartów
# w deploy/observability/values/). Zapytania idą do Lokiego przez proxy API serwera
# (kubectl get --raw), bez port-forwardu; Grafanę test pyta pod http://localhost:3000
# (NodePort 30300) kontem z Secretu grafana-admin.
# Awarie wywołuje fault-runner: errors (logi ERROR w orders) i dwa razy crash (zdarzenie
# BackOff). Crash restartuje orders jak S5, więc alert PodRestarts wysyła e-mail.
# Uruchomienie: uv run --locked pytest tests/observability/test_logs.py
# (kubectl z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.parse
import urllib.request

import pytest

pytestmark = pytest.mark.observability

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
# Usługa loki z chartu Loki w trybie Monolithic (release loki, bez gatewaya).
LOKI_PROXY = "/api/v1/namespaces/monitoring/services/loki:3100/proxy"
LOKI_URL = "http://loki.monitoring.svc:3100"
GRAFANA_URL = "http://localhost:3000"
FAULT_RUNNER = ("exec", "-n", "loadgen", "deploy/fault-runner", "--", "fault-runner")
# Zapytania z kryteriów akceptacji T17.
ERROR_LOGS = '{namespace="shop", container="orders"} | json | level="ERROR"'
BACKOFF_EVENTS = (
    '{job="loki.source.kubernetes_events", namespace="shop"}'
    ' | json | reason="BackOff" | name=~"orders-.*"'
)
WAIT_SECONDS = 120
# Kolejne crashe w ciągu 10 min podwajają back-off kubeleta (10 s, 20 s, 40 s …),
# więc orders wraca później przy powtórzonym przebiegu testu.
RESTART_WAIT_SECONDS = 180


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        pytest.fail(f"kubectl {command}: kod {result.returncode}, {result.stderr}")
    return result


def fault_runner(*args: str) -> None:
    """Polecenie fault-runner w podzie loadgen/fault-runner, do 5 prób."""
    for _ in range(5):
        result = kubectl(*FAULT_RUNNER, *args, check=False)
        if result.returncode == 0:
            return
        # Po restarcie orders usługa dostaje endpoint chwilę po gotowości kontenera.
        time.sleep(2)
    pytest.fail(
        f"fault-runner {' '.join(args)}: kod {result.returncode}, {result.stderr}"
    )


def query_range(query: str, start_ns: int) -> list[tuple[dict, str]]:
    """Wpisy z Lokiego od start_ns do teraz: pary (etykiety strumienia, linia)."""
    params = urllib.parse.urlencode(
        {"query": query, "start": start_ns, "end": time.time_ns(), "limit": 100}
    )
    path = f"{LOKI_PROXY}/loki/api/v1/query_range?{params}"
    body = json.loads(kubectl("get", "--raw", path).stdout)
    assert body["status"] == "success", body
    return [
        (stream["stream"], value[1])
        for stream in body["data"]["result"]
        for value in stream["values"]
    ]


def wait_for_entries(query: str, start_ns: int) -> list[tuple[dict, str]]:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        entries = query_range(query, start_ns)
        if entries:
            return entries
        time.sleep(5)
    pytest.fail(f"{query}: brak wpisów w Lokim po {WAIT_SECONDS} s")


def orders_status() -> tuple[int, bool]:
    """Liczba restartów i gotowość kontenera orders (jedyny pod Deploymentu)."""
    pods = json.loads(
        kubectl(
            "get",
            "pods",
            "-n",
            "shop",
            "-l",
            "app.kubernetes.io/name=orders",
            "-o",
            "json",
        ).stdout
    )["items"]
    running = [pod for pod in pods if "deletionTimestamp" not in pod["metadata"]]
    assert len(running) == 1, [pod["metadata"]["name"] for pod in running]
    status = running[0]["status"].get("containerStatuses", [{}])[0]
    return status.get("restartCount", 0), status.get("ready", False)


def wait_for_orders(restarts: int) -> None:
    """Czeka, aż kontener orders ma co najmniej `restarts` restartów i jest gotowy."""
    deadline = time.monotonic() + RESTART_WAIT_SECONDS
    current = orders_status()
    while time.monotonic() < deadline:
        current = orders_status()
        if current[0] >= restarts and current[1]:
            return
        time.sleep(2)
    pytest.fail(
        f"orders: (restarty, gotowy) = {current}, oczekiwane ({restarts}, True) "
        f"po {RESTART_WAIT_SECONDS} s"
    )


def grafana_get(path: str) -> dict:
    """Odpowiedź JSON API Grafany; konto admina z Secretu grafana-admin."""
    data = json.loads(
        kubectl(
            "get", "secret", "grafana-admin", "-n", "monitoring", "-o", "json"
        ).stdout
    )["data"]
    user, password = (
        base64.b64decode(data[key]).decode() for key in ("admin-user", "admin-password")
    )
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{GRAFANA_URL}{path}", headers={"Authorization": f"Basic {token}"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    result = kubectl("get", "--raw", "/readyz", check=False)
    if result.returncode != 0:
        pytest.fail(f"Klaster {KUBE_CONTEXT} niedostępny (make up): {result.stderr}")
    kubectl(
        "wait",
        "-n",
        "monitoring",
        "--for=condition=Ready",
        "pod",
        "-l",
        "app.kubernetes.io/name=loki",
        "--timeout=45s",
    )
    kubectl("rollout", "status", "-n", "monitoring", "daemonset/alloy", "--timeout=45s")
    kubectl(
        "wait",
        "-n",
        "loadgen",
        "--for=condition=Available",
        "deployment/fault-runner",
        "--timeout=30s",
    )


def test_grafana_has_loki_datasource():
    source = grafana_get("/api/datasources/uid/loki")
    assert (source["type"], source["url"]) == ("loki", LOKI_URL), source
    # Grafana sprawdza połączenie zapytaniem do Lokiego.
    health = grafana_get("/api/datasources/uid/loki/health")
    assert health["status"] == "OK", health


def test_orders_errors_fault_gives_error_logs():
    # Sekunda zapasu na różnicę zegarów i zaokrąglenia znaczników czasu.
    start_ns = time.time_ns() - 1_000_000_000
    fault_runner("fault", "errors", "--seconds", "30", "--param", "ratio=1")
    try:
        # POST /order frontendu woła POST /orders, a ten w czasie awarii zwraca 500.
        fault_runner("spike", "--users", "1", "--seconds", "15")
        entries = wait_for_entries(ERROR_LOGS, start_ns)
    finally:
        fault_runner("stop")
    assert all(labels["pod"].startswith("orders-") for labels, _ in entries), entries
    logged = [json.loads(line) for _, line in entries]
    assert any(
        entry["status"] == 500 and entry["route"] == "/orders" for entry in logged
    ), logged[:5]
    # level to też etykieta strumienia (stage.labels w Alloy), nie tylko pole z | json.
    selector = '{namespace="shop", container="orders", level="ERROR"}'
    assert query_range(selector, start_ns), f"{selector}: brak wpisów"


def test_backoff_event_after_repeated_crash():
    start_ns = time.time_ns() - 1_000_000_000
    restarts, _ = orders_status()
    wait_for_orders(restarts)
    crashes = 0
    try:
        # Pierwszy crash kubelet restartuje od razu. Drugi w ciągu 10 min trafia w okno
        # back-off (10 s), więc kubelet zapisuje zdarzenie BackOff.
        fault_runner("fault", "crash")
        crashes += 1
        wait_for_orders(restarts + crashes)
        fault_runner("fault", "crash")
        crashes += 1
        entries = wait_for_entries(BACKOFF_EVENTS, start_ns)
    finally:
        # Następne testy potrzebują działającego orders.
        wait_for_orders(restarts + crashes)
    event = json.loads(entries[0][1])
    assert (event["kind"], event["type"]) == ("Pod", "Warning"), event
    assert "Back-off restarting failed container orders" in event["msg"], event
```

2. `tests/security/test_rbac.py`: zastosuj łatę (`git apply` albo ręcznie; wynik identyczny, sformatowany ruffem). 12 nowych przypadków `test_permission_matrix` z identyfikatorami `sa:monitoring/alloy-<czasownik>-<zasób>-<namespace|klaster>`. Wiersze odmowy łapią powrót do domyślnej ClusterRole chartu (odczyt secrets i configmaps w całym klastrze), a wiersze zgody — zbyt wąską Role, z którą Alloy nie zbiera logów ani zdarzeń.

```diff
--- a/tests/security/test_rbac.py
+++ b/tests/security/test_rbac.py
@@ -60,6 +60,10 @@
     ("patch", "deployments.apps"),
     ("create", "configmaps"),
 ]
+# Konto Alloy (T17): Role tylko w namespace'ach z logami
+# (deploy/observability/values/alloy.yaml).
+ALLOY = "sa:monitoring/alloy"
+ALLOY_NAMESPACES = ("shop", "loadgen", "aiops", "intruder")
 
 # (kto, czasownik, zasób[/podzasób], namespace albo None = cały klaster, odpowiedź)
 MATRIX = [
@@ -98,6 +102,17 @@
         for namespace, name in SERVICE_ACCOUNTS
         for verb, resource in (("list", "secrets"), ("get", "pods"))
     ],
+    # Alloy (T17): pody i zdarzenia w namespace'ach z logami; bez secrets, configmaps
+    # i innych namespace'ów (domyślna ClusterRole chartu Alloy czyta secrets w klastrze)
+    *[
+        (ALLOY, verb, resource, namespace, True)
+        for namespace in ALLOY_NAMESPACES
+        for verb, resource in (("list", "pods"), ("watch", "events"))
+    ],
+    (ALLOY, "list", "secrets", "shop", False),
+    (ALLOY, "list", "secrets", None, False),
+    (ALLOY, "list", "configmaps", "shop", False),
+    (ALLOY, "list", "pods", "kube-system", False),
     # kontrola: użytkownik bez grupy zespołu
     ("bez-zespolu", "list", "pods", "shop", False),
 ]
```

3. Sprawdzenie:
   - `make lint` → zielone;
   - `mise exec -- uv run --locked pytest tests/observability/test_logs.py --collect-only -q` → 3 testy;
   - na klastrze z Tasków 1–2: `mise exec -- uv run --locked pytest tests/observability/test_logs.py -v` → `3 passed` (ok. 1 min), potem `mise exec -- uv run --locked pytest tests/security/test_rbac.py -v -k alloy` → `12 passed`.

### Task 4: Dokumentacja
**Commit:** docs: Loki i Alloy (T17) w README, architekturze i modelu zagrożeń

**Files:**
- Modify: `README.md`
- Modify: `docs/architektura.md`
- Modify: `docs/bezpieczenstwo.md`

1. `README.md`:
   - linia 41: `Prometheus i Grafana, obrazy :dev` zamień na `Prometheus, Grafana, Loki i Alloy, obrazy :dev`;
   - linię 54 zastąp: ``make observability  # w monitoring (najpierw make secrets): kube-prometheus-stack (Prometheus, Alertmanager, Grafana), Loki i Alloy``;
   - w linii 78 po `(ok. 1 min, ruch z fault-runner spike);` wstaw ` logi i zdarzenia (T17): źródło Loki w Grafanie, ERROR orders po fault errors, BackOff po dwóch fault crash (ok. 1 min; orders restartuje się dwa razy, e-mail PodRestarts);`. Reszta linii bez zmian;
   - po bloku kodu sekcji „Alerty (Mailpit)” (linia 126, zamykające ```` ``` ````) i pustej linii wstaw sekcję poniżej, przed `## Jak pracujemy`, z pustą linią po niej:

```markdown
### Logi i zdarzenia (Loki)

Grafana Alloy (DaemonSet w monitoring) wysyła do Lokiego logi kontenerów i zdarzenia Kubernetes z shop, loadgen, aiops i intruder; Loki trzyma je 72 h. Przegląd w Grafanie: Explore, źródło Loki. Etykiety i pola: [docs/architektura.md](docs/architektura.md#kontrakt-metryk-i-logów).

- `{namespace="shop", container="orders"} | json | level="ERROR"`: błędy orders, np. po S3 (`fault errors`);
- `{job="loki.source.kubernetes_events", namespace="shop"} | json | type="Warning"`: zdarzenia Warning, np. `BackOff` po drugim `fault crash` w ciągu 10 min.
```

2. `docs/architektura.md`:
   - linie 13–14 (tabela „Komponenty i wersje”) zastąp:

```markdown
| Loki (chart `loki` z `grafana-community/helm-charts`, OCI `ghcr.io/grafana-community/helm-charts`; SingleBinary, w chartcie `deploymentMode: Monolithic`) | przypięta w `versions.env` | monitoring | T17 |
| Grafana Alloy (chart `alloy` z `grafana/helm-charts`, OCI `ghcr.io/grafana/helm-charts`; DaemonSet) | przypięta w `versions.env` | monitoring | T17 |
```

   - na końcu linii 24 (po `… gdy tag wersji wskazuje inny digest.`) dopisz: `` Tak samo `make observability` instaluje kube-prometheus-stack (T16) oraz Loki i Alloy (T17); oba charty T17 pochodzą z rejestrów OCI.``;
   - w linii 93 po zdaniu `… ani chartów z T16 i T17: mają własne konta i RBAC.` wstaw: `` Alloy (T17) ma zamiast domyślnej ClusterRole chartu (m.in. odczyt secrets i configmaps w całym klastrze) Role `alloy` w shop, loadgen, aiops i intruder: get, list, watch na pods i events (`rbac` w `deploy/observability/values/alloy.yaml`); pilnują tego wiersze `sa:monitoring/alloy` w `test_permission_matrix`.``;
   - po akapicie `Test: tests/observability/test_metrics.py …` (linia 202) i pustej linii, przed `- **Detektor (T24).**`, wstaw blok poniżej z pustą linią po nim:

```markdown
- **Logi i zdarzenia (T17).** Loki i Grafana Alloy w monitoring (`make observability`, krok `make up`; wartości w `deploy/observability/values/loki.yaml` i `alloy.yaml`):
  - Loki (release `loki`): tryb SingleBinary (w chartcie `deploymentMode: Monolithic`), jeden pod `loki-0` z danymi w systemie plików na PVC 5 Gi, retencja 72 h (compactor), bez gatewaya, memcached i canary. Usługa `loki.monitoring.svc:3100` bez uwierzytelnienia (`auth_enabled: false`, jeden tenant): zapisuje Alloy (`/loki/api/v1/push`), czytają Grafana i anomaly-detector (T24).
  - Logi (Alloy, release `alloy`, DaemonSet na workerach): pliki `/var/log/pods` podów z shop, loadgen, aiops i intruder z węzła danej instancji (hostPath `/var/log` tylko do odczytu). Etykiety strumienia: `namespace`, `pod`, `container`, `stream` (`stdout`, `stderr`) i `level` z pola `level` linii JSON z kontraktu wyżej; linia spoza JSON nie ma `level`. Logów z monitoring i kube-system Alloy nie zbiera.
  - Zdarzenia Kubernetes z tych samych namespace'ów (`loki.source.kubernetes_events`, `log_format = "json"`): etykiety `job="loki.source.kubernetes_events"`, `namespace` (obiektu zdarzenia) i `instance`, linia JSON z polami m.in. `name`, `kind`, `reason`, `type`, `count`, `msg`, `sourcecomponent`, `sourcehost`; czas wpisu to ostatnie wystąpienie zdarzenia. Instancje Alloy tworzą klaster, więc każdy namespace czyta jedna z nich, a zdarzenie trafia do Lokiego raz.
  - Grafana: źródło `Loki` (uid `loki`, `http://loki.monitoring.svc:3100`) z `grafana.additionalDataSources` w wartościach kube-prometheus-stack.
  - Zapytania: `{namespace="shop", container="orders"} | json | level="ERROR"` (błędy orders), `{job="loki.source.kubernetes_events", namespace="shop"} | json | reason="BackOff"` (zdarzenia `BackOff`). Kubelet zapisuje `BackOff` dopiero przy drugim crashu kontenera w ciągu 10 min: po pierwszym restartuje od razu, potem czeka 10 s, 20 s, 40 s… (do 5 min).

Test: `tests/observability/test_logs.py` (marker `observability`); na działającym klastrze `uv run --locked pytest tests/observability/test_logs.py`. Sprawdza źródło Loki w Grafanie (`/api/datasources/uid/loki/health`), logi `level="ERROR"` orders po `fault-runner fault errors` (zapytanie z kryterium T17 i etykieta `level`) oraz zdarzenie `BackOff` po dwóch `fault-runner fault crash`. Test restartuje orders dwa razy, jak S5, więc alert PodRestarts wysyła e-mail.
```

   - linia 287 (wiersz `Makefile` w „Strukturze repozytorium”): `observability (T16)` zamień na `observability (T16, T17)`;
   - linia 302 (wiersz `tests/`): `(T11–T14, T16, T18, T26, T27)` zamień na `(T11–T14, T16–T18, T26, T27)`.

3. `docs/bezpieczenstwo.md`:
   - po linii 87 (wiersz `| Z3 | role developer i sre-readonly: …`) wstaw wiersz:

```markdown
| Z3 | konto `monitoring/alloy` (T17): Role tylko z get, list, watch na pods i events w shop, loadgen, aiops i intruder, bez domyślnej ClusterRole chartu (odczyt secrets i configmaps w całym klastrze) | T17 | `tests/security/test_rbac.py::test_permission_matrix` (wiersze `sa:monitoring/alloy-…`) | działa |
```

   - linię 110 (R1) zastąp:

```markdown
| R1 | Namespace monitoring nie ma default-deny i ma PSA `privileged`. Loki (T17) przyjmuje zapisy i zapytania bez uwierzytelnienia (`auth_enabled: false`), więc każdy pod w klastrze może czytać logi i zdarzenia z shop, loadgen, aiops i intruder albo dopisać fałszywe wpisy. | Charty z T16–T19 łączą się z wieloma celami w klastrze, a node-exporter i Alloy potrzebują dostępu do hosta. W monitoring nie ma własnego kodu projektu. Logi z kontraktu (`libs/observability`) nie zawierają tokenów ani treści zamówień; detektor (T24) bierze z Lokiego tylko kontekst do logu analizy, a alerty liczy z metryk. | overlay `cloud` (T29) |
```

   - linię 111 (R2) zastąp:

```markdown
| R2 | node-exporter i Alloy działają z uprawnieniami do hosta. Ucieczka z ich kontenera daje węzeł. | Bez tego nie ma metryk węzła ani logów kontenerów. Wersje chartów są przypięte w `platform/versions.env`. node-exporter (T16): `hostNetwork`, `hostPID`, hostPath `/`, `/proc` i `/sys` tylko do odczytu, UID 65534, bez eskalacji uprawnień i bez capabilities (`deploy/observability/values/kube-prometheus-stack.yaml`). Alloy (T17): jedyny wolumen hosta to `/var/log` tylko do odczytu, bez `hostNetwork` i `hostPID`; UID 473 z grupą 0 zamiast roota (logi w `/var/log/pods` mają `0640 root:root` w katalogu `0750`), bez eskalacji uprawnień i bez capabilities, system plików kontenera tylko do odczytu; RBAC tylko na pods i events w czterech namespace'ach z logami (`deploy/observability/values/alloy.yaml`). | overlay `cloud` (T29) |
```

   Linia 3 („Stan na …”) się nie zmienia (T14–T26 też jej nie zmieniały).
4. Sprawdzenie: `make lint` → zielone; `git diff --stat` → tylko trzy pliki z tego Taska.

## Critical files & anchors

- `Makefile`: zmienne chartów (15–17), cel `observability` (106–114); nowe polecenia stoją po kube-prometheus-stack, Alloy na końcu.
- `deploy/observability/values/kube-prometheus-stack.yaml`: blok `grafana:` (70–83), źródło wchodzi po `service:`.
- `tests/observability/test_metrics.py` (45–98): wzorzec `kubectl()`, proxy API serwera i fixture `cluster`.
- `tests/security/test_rbac.py`: stałe (46–62), `MATRIX` (65–103), `identity()` dla `sa:` (123–128).
- `docs/bezpieczenstwo.md:110-111`: R1 i R2, które T17 zmienia.

## Verification

Korzeń repozytorium, gałąź `t17-logi-zdarzenia` z Taskami 1–4, klaster `kind-secure-k8s-aiops`. Skróty: `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`, `L=/api/v1/namespaces/monitoring/services/loki:3100/proxy`. „Bez internetu” znaczy klaster, w którym intruder nie łączy się z `https://1.1.1.1/`; wtedy 4 przypadki `test_egress_to_internet_is_denied` są pomijane. Jeśli liczba albo linia się nie zgadza, zatrzymaj się i zgłoś wynik.

1. Bez klastra:
   - `make lint && make unit && make manifests && make trivy-config` → kod 0, `unit` → `96 passed`;
   - `mise exec -- uv run --locked pytest -m security tests --collect-only -q | tail -n 1` → `117/132 tests collected (15 deselected)`; `-m observability` → `15/132 tests collected (117 deselected)`. Inna baza na `main`: różnica względem `main` musi wynosić +13 (security) i +3 (observability).
2. Kryteria akceptacji na działającym klastrze:

   ```bash
   make observability && make deploy
   mise exec -- uv run --locked pytest tests/observability/test_logs.py -v 2>&1 | tee reports/t17-logi.txt
   make test-security 2>&1 | tee reports/t17-security.txt
   ```

   - `3 passed`; `make test-security` → `117 passed` (bez internetu `113 passed, 4 skipped`).
3. Zdarzenie trafia do Lokiego raz, a instancje Alloy tworzą klaster:

   ```bash
   python3 -c 'import datetime, json; now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); print(json.dumps({"apiVersion": "v1", "kind": "Event", "metadata": {"generateName": "t17-dup-"}, "involvedObject": {"apiVersion": "v1", "kind": "Pod", "name": "t17-dup", "namespace": "shop"}, "reason": "T17Dup", "message": "kontrola duplikatów T17", "type": "Normal", "source": {"component": "t17"}, "firstTimestamp": now, "lastTimestamp": now, "count": 1}))' | $K -n shop create -f -
   sleep 20
   q=$(python3 -c 'import urllib.parse; print(urllib.parse.quote("{job=\"loki.source.kubernetes_events\", namespace=\"shop\"} | json | reason=\"T17Dup\""))')
   $K get --raw "$L/loki/api/v1/query_range?query=$q&since=10m" | python3 -c 'import json,sys; print(sum(len(s["values"]) for s in json.load(sys.stdin)["data"]["result"]))'
   for p in $($K -n monitoring get pods -l app.kubernetes.io/name=alloy -o name); do $K get --raw "/api/v1/namespaces/monitoring/pods/${p#pod/}:12345/proxy/api/v0/web/peers" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))'; done
   ```

   - liczba wpisów: `1`;
   - każdy pod Alloy widzi `2` peerów.
4. Ponowne `make up` niczego nie zmienia w monitoring:

   ```bash
   $K -n monitoring get pods -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,RESTARTS:.status.containerStatuses[*].restartCount > reports/t17-przed.txt
   make up
   $K -n monitoring get pods -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,RESTARTS:.status.containerStatuses[*].restartCount > reports/t17-po.txt
   diff reports/t17-przed.txt reports/t17-po.txt && echo bez-zmian
   ```

   - `bez-zmian`.
5. Od zera (definicja ukończenia):

   ```bash
   make down && time make up
   mise exec -- uv run --locked pytest tests/observability -v 2>&1 | tee reports/t17-swiezy.txt
   make test-security
   ```

   - `make up` → kod 0, czas `real` zapisz do opisu PR;
   - `tests/observability` → `14 passed, 1 skipped` (`test_traffic` czeka na 65 min Locusta);
   - `make test-security` → `117 passed` (bez internetu `113 passed, 4 skipped`).

## Po dostarczeniu (GitHub)

Wykonuje główny agent po Verification i po code review bez CRITICAL/HIGH.

1. PR z gałęzi `t17-logi-zdarzenia` do `main`, tytuł „T17 · Logi i zdarzenia: Loki + Grafana Alloy”, w treści `Closes #17`. Opis podaje: charty z OCI i piny (cooldown 7 dni: Loki 21.2.3 zamiast 21.4.3, ta sama wersja Loki 3.7.10); utwardzenie Alloy (Role zamiast ClusterRole z odczytem secrets, UID 473 z grupą 0, bez CRD PodLogs, bez statystyk); wyłączony sidecar reguł Lokiego; clustering dla zdarzeń; dlaczego test robi dwa crashe (`BackOff` dopiero przy drugim) i jego skutki uboczne (e-mail PodRestarts); czas `make up` z kroku 5 Verification i maszynę (README nadal podaje pomiar z R3).
2. Komentarz w #17: odhaczone kryteria z wynikiem z `reports/t17-swiezy.txt` (`test_orders_errors_fault_gives_error_logs`, `test_backoff_event_after_repeated_crash`).
3. Komentarz w #22: „T17: źródło Loki ma uid `loki`. Etykiety logów: `namespace`, `pod`, `container`, `stream`, `level`; zdarzenia: `{job="loki.source.kubernetes_events"}` z polami JSON `reason`, `type`, `name`, `kind`, `msg` (`| json`).”
4. Komentarz w #24: „T17: Loki pod `http://loki.monitoring.svc:3100` bez uwierzytelnienia (bez `X-Scope-OrgID`); egress aiops → Loki :3100 jest już w `deploy/base/networkpolicies/aiops.yaml`. Ostatnie zdarzenia Warning dla usługi: `{job="loki.source.kubernetes_events", namespace="shop"} | json | type="Warning" | name=~"orders-.*"` (`name` to nazwa obiektu zdarzenia, np. poda).”
5. Komentarz w #28: „T17: `tests/observability/test_logs.py` pyta Grafanę pod `http://localhost:3000` (port z `extraPortMappings` kind) i dwa razy restartuje orders; `make observability` pobiera charty z `ghcr.io/grafana-community/helm-charts` i `ghcr.io/grafana/helm-charts`.”

## Assumptions & contingencies

- Wersje z 7-dniowym cooldownem (Loki 21.2.3, Alloy 1.16.0). Jeśli właściciel woli najnowszą: Loki 21.4.3, digest `sha256:95f8514e0b4ab731676824fbd335ba24cbecf744b07052204d484eb64377d0c5` (ta sama aplikacja 3.7.10, wartości z Task 1 bez zmian) i zdanie o cooldownie w `versions.env` do usunięcia.
- Utwardzenie Alloy ponad wartości domyślne chartu i wiersze w `test_rbac.py` wynikają z R2 („T17: przegląd wartości chartu Alloy”) i z reguły `docs/bezpieczenstwo.md:5` (nowe uprawnienie aktualizuje macierz).
- Test zdarzeń robi dwa crashe orders, bo kryterium podaje `BackOff`, a jeden crash go nie daje.
- Logi i zdarzenia tylko z czterech namespace'ów z issue; bez NetworkPolicy dla Lokiego (R1, T29).

Plan awaryjny:
- **`helm upgrade` kończy się błędem o digeście:** zatrzymaj się i zgłoś komunikat; nie zmieniaj pinów.
- **Inna lista obiektów z `helm template` niż w Task 1 albo Task 2:** zatrzymaj się i zgłoś listę.
- **`loki-0` nie jest Ready w 10 min:** `$K -n monitoring logs loki-0` i `$K -n monitoring describe pod loki-0`; zatrzymaj się i zgłoś pierwszy błąd konfiguracji z logu.
- **Alloy w logu ma `permission denied` na `/var/log/pods`:** w `alloy.securityContext` ustaw `runAsUser: 0` i `runAsNonRoot: false` (reszta bez zmian), w R2 (Task 4) zamiast „UID 473 z grupą 0 zamiast roota (…)” wpisz „UID 0 bez capabilities (pliki logów należą do roota)”, w opisie PR podaj komunikat.
- **Alloy w logu ma `forbidden` dla zasobu spoza `pods` i `events`:** dopisz ten zasób do `rbac.rules` tylko z `get, list, watch`, nigdy `secrets` ani `configmaps`; dopisz wiersz zgody do `MATRIX` i zasób do opisu Role w Task 4.
- **Pod Alloy w `CrashLoopBackOff` z błędem składni:** popraw konfigurację według komunikatu tylko wtedy, gdy odbiega od treści z Task 2 (literówka przy przepisywaniu); inaczej zatrzymaj się i zgłoś komunikat.
- **Brak źródła `Loki` w Grafanie po `make observability`:** `$K -n monitoring logs deploy/kube-prometheus-stack-grafana -c grafana-sc-datasources --tail 50`; raz `$K -n monitoring rollout restart deploy/kube-prometheus-stack-grafana`, potem health z Task 1; dalej brak → zatrzymaj się i zgłoś.
- **`test_backoff_event_after_repeated_crash` nie widzi `BackOff` w 120 s:** `$K -n shop get events --field-selector reason=BackOff`. Zdarzenie jest w API → zgłoś log `$K -n monitoring logs ds/alloy -c alloy | grep -i event`. Nie ma go w API → zatrzymaj się i zgłoś (inne zachowanie back-off kubeleta).
- **Krok 3 Verification: peerów `1`:** `$K -n monitoring get endpoints alloy-cluster`; zatrzymaj się i zgłoś. Liczba wpisów `2` przy peerach `2`: zgłoś (duplikaty mimo clusteringu).
- **`make up` pada na zajętym porcie:** zwolnij 8080, 3000 albo 8025 na `127.0.0.1` i powtórz.
