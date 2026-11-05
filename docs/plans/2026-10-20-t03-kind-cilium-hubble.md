# T03 · Klaster kind z Cilium i Hubble (issue #3)

## Context

Issue #3 (T03, R1, Sprint 1) wymaga lokalnego klastra kind (1 control-plane + 2 workery), w którym Cilium egzekwuje NetworkPolicy, a Hubble raportuje przepływy i odrzucenia; kolejność instalacji: kind → chart `prometheus-operator-crds` → Cilium 1.20.3 z `platform/cilium/values.yaml`; cele `make cluster` (idempotentny) i `make hubble-ui`. Kryteria akceptacji: `cilium status --wait` OK dla wszystkich komponentów, `hubble observe --last 20` pokazuje przepływy, `cilium connectivity test` przechodzi (testy wymagające internetu wolno pominąć z adnotacją). Dziś `platform/` zawiera tylko `.gitkeep`, a `Makefile` ma tylko cel `doctor`; narzędzia (kind 0.33.0, helm 4.3.1, cilium-cli 0.20.1, hubble 1.20.2, kubectl 1.37.1) są przypięte w `mise.toml`. Stan docelowy: działające `make cluster` / `make hubble-ui` (T04 woła `make cluster` z `make up`) i kontrakt metryk Cilium/Hubble w `docs/architektura.md`, z którego korzystają T12, T16 i T19.

## Approach

### Task 1: Konfiguracja kind i Cilium oraz cele make cluster i hubble-ui
**Commit:** feat(platform): klaster kind z Cilium i Hubble (make cluster, make hubble-ui)

**Files:**
- Create: `platform/versions.env`
- Create: `platform/kind/cluster.yaml`
- Create: `platform/cilium/values.yaml`
- Modify: `Makefile`
- Delete: `platform/.gitkeep`

1. Utwórz `platform/versions.env`. Format `KLUCZ=wartość` bez spacji i cudzysłowów, bo plik czyta `include` w Makefile (a skrypty T04 mogą go `source`'ować). `.gitignore` ma `*.env` i wyjątek `!platform/versions.env` – plik będzie śledzony (sprawdzone `git check-ignore`). Treść:

```
# Wersje chartów Helm i obrazów zewnętrznych (T03, T04): jedno źródło dla Makefile i skryptów.
# Format KLUCZ=wartość, bez spacji i cudzysłowów. Wersja Cilium jest też w docs/architektura.md – zmieniaj obie.
CILIUM_VERSION=1.20.3
PROMETHEUS_OPERATOR_CRDS_VERSION=32.0.1
```

   `32.0.1` to najnowsza stabilna wersja chartu (operator v0.94.1); chart zawiera wyłącznie 10 CRD `monitoring.coreos.com`.

2. Utwórz `platform/kind/cluster.yaml` bez pola `name` (nazwę nadaje Makefile przez `--name`, jedno źródło). Obraz węzła: `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed` – zbudowany dla kind 0.33.0 (release notes kind v0.33.0), digest zweryfikowany w rejestrze; Kubernetes 1.36 to najnowsza wersja z macierzy testów Cilium 1.20 (1.33–1.36). Treść:

```yaml
# Klaster kind (T03). Twórz przez `make cluster`: Makefile nadaje nazwę i instaluje Cilium.
# Bez domyślnego CNI węzły są NotReady, dopóki Cilium nie wystartuje.
# Kubernetes 1.36 zamiast domyślnego w kind 0.33.0 1.37: Cilium 1.20 jest testowany na 1.33–1.36 (docs/architektura.md).
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
nodes:
  - role: control-plane
    image: kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed
    # NodePorty z docs/architektura.md („Dostęp z hosta”), dostępne tylko z 127.0.0.1.
    extraPortMappings:
      - containerPort: 30080 # frontend
        hostPort: 8080
        listenAddress: "127.0.0.1"
        protocol: TCP
      - containerPort: 30300 # Grafana
        hostPort: 3000
        listenAddress: "127.0.0.1"
        protocol: TCP
      - containerPort: 30825 # Mailpit UI
        hostPort: 8025
        listenAddress: "127.0.0.1"
        protocol: TCP
  - role: worker
    image: kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed
  - role: worker
    image: kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed
```

   kube-proxy zostaje (domyślny `kubeProxyMode`), więc Cilium działa z domyślnym `kubeProxyReplacement: "false"` i nie potrzebuje `k8sServiceHost`; NodePort jest otwarty na każdym węźle, także na control-plane, do którego prowadzą mapowania.

3. Utwórz `platform/cilium/values.yaml` – dokładnie te klucze, reszta z domyślnych chartu 1.20.3 (render `helm template` z tymi values sprawdzony: ServiceMonitory `cilium-agent` → Service `cilium-agent` :9962, `cilium-operator` → :9963, `hubble` → Service `hubble-metrics` :9965; w ConfigMap `cilium-config` klucz `hubble-metrics` z sześcioma wpisami; `routing-mode: tunnel`, `ipam: kubernetes`). Składnia `labelsContext` wg docs.cilium.io (Hubble metrics → Context Options): opcja po dwukropku, wartości po przecinku; etykiety są zawsze obecne, puste, gdy końcem przepływu nie jest pod. `image.pullPolicy` ma w chartcie tę samą wartość domyślną – zostaje jawnie, bo wymaga go issue. Treść:

```yaml
# Wartości chartu Cilium (T03). Wersja chartu: CILIUM_VERSION w platform/versions.env; instalacja: make cluster.
# ServiceMonitory wymagają CRD monitoring.coreos.com/v1 zainstalowanych przed Cilium (chart prometheus-operator-crds).
ipam:
  mode: kubernetes # CIDR-y podów przydziela Kubernetes (podSubnet kind)
image:
  pullPolicy: IfNotPresent
# Metryki agenta i operatora z ServiceMonitorami (Prometheus w T16).
prometheus:
  enabled: true
  serviceMonitor:
    enabled: true
operator:
  prometheus:
    enabled: true
    serviceMonitor:
      enabled: true
hubble:
  enabled: true
  relay:
    enabled: true
  ui:
    enabled: true
  metrics:
    # Kontekst źródła i celu jako osobne etykiety (docs.cilium.io: Hubble metrics → Context Options).
    # Kontrakt dla reguł T16 (service:policy_drops:rate1m) opisuje docs/architektura.md.
    enabled:
      - "dns:labelsContext=source_namespace,source_workload,destination_namespace,destination_workload"
      - "drop:labelsContext=source_namespace,source_workload,destination_namespace,destination_workload"
      - "tcp:labelsContext=source_namespace,source_workload,destination_namespace,destination_workload"
      - "flow:labelsContext=source_namespace,source_workload,destination_namespace,destination_workload"
      - "port-distribution:labelsContext=source_namespace,source_workload,destination_namespace,destination_workload"
      - "icmp:labelsContext=source_namespace,source_workload,destination_namespace,destination_workload"
    serviceMonitor:
      enabled: true
```

4. Zastąp treść `Makefile` poniższą (wcięcia receptur to tabulatory; nagłówek z `export PATH` i cel `doctor` bez zmian):

```make
# Narzędzia w wersjach z mise.toml mają pierwszeństwo przed systemowymi,
# także gdy mise nie jest aktywowane w powłoce.
export PATH := $(shell mise bin-paths 2>/dev/null | tr '\n' ':')$(PATH)

# Wersje chartów i obrazów zewnętrznych (T03, T04).
include platform/versions.env

CLUSTER_NAME := secure-k8s-aiops
KUBE_CONTEXT := kind-$(CLUSTER_NAME)
CILIUM_CHART := oci://quay.io/cilium/charts/cilium
PROMETHEUS_OPERATOR_CRDS_CHART := oci://ghcr.io/prometheus-community/charts/prometheus-operator-crds

.PHONY: doctor cluster hubble-ui

# Sprawdza narzędzia z mise.toml, dostęp do Dockera bez sudo, pamięć Dockera i limity inotify.
doctor:
	@bash scripts/doctor.sh

# Klaster kind z Cilium i Hubble. Idempotentny: istniejącego klastra nie tworzy ponownie,
# a helm upgrade --install doprowadza CRD i Cilium do wersji z platform/versions.env.
# CRD prometheus-operator (ServiceMonitor) muszą istnieć przed instalacją Cilium.
cluster:
	@if kind get clusters | grep -qx '$(CLUSTER_NAME)'; then \
		echo "Klaster $(CLUSTER_NAME) już istnieje."; \
	else \
		kind create cluster --name '$(CLUSTER_NAME)' --config platform/kind/cluster.yaml; \
	fi
	helm upgrade --install prometheus-operator-crds $(PROMETHEUS_OPERATOR_CRDS_CHART) \
		--version $(PROMETHEUS_OPERATOR_CRDS_VERSION) \
		--kube-context $(KUBE_CONTEXT) --namespace kube-system --wait
	helm upgrade --install cilium $(CILIUM_CHART) \
		--version $(CILIUM_VERSION) \
		--kube-context $(KUBE_CONTEXT) --namespace kube-system \
		--values platform/cilium/values.yaml --wait --timeout 10m
	cilium status --context $(KUBE_CONTEXT) --wait
	kubectl --context $(KUBE_CONTEXT) wait --for=condition=Ready nodes --all --timeout=5m

# Hubble UI w przeglądarce: port-forward na localhost:12000, Ctrl+C kończy.
hubble-ui:
	cilium hubble ui --context $(KUBE_CONTEXT)
```

   Decyzje wpisane w recepturę (nie zmieniaj):
   - `kind create cluster` bez `--wait`: bez CNI węzły nie osiągną Ready, kind czekałby do timeoutu.
   - Oba `helm upgrade --install` wykonują się zawsze: na działającym klastrze nie zmieniają podów (szablony podów w chartcie Cilium nie mają adnotacji checksum, `rollOutCiliumPods` domyślnie false, a sekrety `cilium-ca` i `hubble-server-certs` chart używa ponownie przez `lookup`), a po przerwanym pierwszym uruchomieniu dokańczają instalację.
   - `--wait` podane jawnie: w Helm 4.3.1 bez flagi strategia to `hookOnly` (Helm nie czeka na zasoby), samo `--wait` = `watcher`. Dla CRD `watcher` czeka na `Established`, więc instalacja Cilium widzi `monitoring.coreos.com/v1` – bez tego render ServiceMonitorów w chartcie Cilium kończy się błędem.
   - `--timeout 10m` tylko dla Cilium: pierwszy start pobiera obrazy na trzech węzłach (domyślne 5m wystarcza dla CRD).
   - Charty z rejestrów OCI: bez `helm repo add`/`helm repo update`, czyli bez globalnego stanu w konfiguracji Helma użytkownika.
   - Każde polecenie z jawnym kontekstem (`--kube-context` / `--context`), żeby nie dotknąć innego klastra z kubeconfiga.
   - Release `prometheus-operator-crds` w `kube-system`: namespace `monitoring` z etykietami PSA tworzy T04 (Kustomize), `--create-namespace` by go wyprzedził.
   - Release Cilium nazywa się `cilium` (nazwa, której oczekuje cilium-cli).
   - Komunikat `No kind clusters found.` z `kind get clusters` przy pierwszym uruchomieniu zostaje widoczny (stderr nie jest wyciszany, żeby błędy Dockera były widoczne).

5. Usuń `platform/.gitkeep` – katalog ma już śledzone pliki.

### Task 2: Dokumentacja klastra lokalnego i kontraktu Cilium/Hubble
**Commit:** docs: klaster lokalny i kontrakt metryk Cilium/Hubble (T03)

**Files:**
- Modify: `docs/architektura.md`
- Modify: `docs/karta-projektu.md`
- Modify: `README.md`

1. `docs/architektura.md`, tabela „Komponenty i wersje”, wiersz kind (linia 9): zamień `kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5` na `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`; kolumny wersji (0.33.0) i zadania (T03) bez zmian.
2. `docs/architektura.md`: po akapicie z linii 23 (zaczyna się od „Wersje oznaczone „przypięta””) wstaw nowy akapit uzasadniający obniżenie wersji:

```markdown
Kubernetes 1.36 zamiast 1.37 to świadomy downgrade o jedną wersję (T03). kind 0.33.0 domyślnie stawia Kubernetes 1.37.0, ale Cilium 1.20 deklaruje testy e2e tylko dla Kubernetes 1.33–1.36 ([wymagania Cilium 1.20](https://docs.cilium.io/en/v1.20/network/kubernetes/requirements/)), więc węzły używają obrazu `kindest/node:v1.36.4`, zbudowanego dla kind 0.33.0. kubectl 1.37.1 z `mise.toml` zostaje, bo odchylenie o jedną wersję jest dozwolone. Na 1.37 przechodzimy, gdy przypięta wersja Cilium obejmie ją testami.
```

3. `docs/architektura.md`, sekcja „Dostęp z hosta” (linia 38): przed zdaniem „Nie ma kontrolera Ingress…” wstaw osobny akapit: `` Klaster kind `secure-k8s-aiops` (kontekst kubectl `kind-secure-k8s-aiops`) tworzy `make cluster` (T03). ``
4. `docs/architektura.md`, sekcja „Kontrakt metryk i logów”: między punktem `**Logi.**` (linia 73) a `**Reguły nagrywające (T16).**` (linia 74) wstaw punkt:

```markdown
- **Cilium i Hubble (T03).** CRD prometheus-operator instaluje T03 (chart `prometheus-operator-crds`, wersja w `platform/versions.env`), więc kube-prometheus-stack (T16) instaluje się bez CRD. ServiceMonitory w `kube-system`, bez dodatkowych etykiet: `cilium-agent` (port 9962), `cilium-operator` (9963) i `hubble` (9965); Prometheus (T16) wybiera ServiceMonitory ze wszystkich namespace'ów, bez filtra etykiet. Metryki Hubble `dns`, `drop`, `tcp`, `flow`, `port-distribution` i `icmp` mają etykiety `source_namespace`, `source_workload`, `destination_namespace` i `destination_workload` (puste, gdy końcem przepływu nie jest pod). Odrzucenia przez NetworkPolicy to `hubble_drop_total{reason="POLICY_DENIED"}`.
```

5. `docs/karta-projektu.md`, tabela „Technologie”, wiersz „Klaster” (linia 113): zastąp cały wiersz wierszem `| Klaster | kind 0.33 (Kubernetes 1.36), 3 węzły | działa lokalnie i w CI, konfiguracja w jednym pliku; Kubernetes 1.36 zamiast domyślnego w kind 1.37, bo Cilium 1.20 jest testowany na Kubernetes 1.33–1.36 |`.
6. `README.md`: po sekcji „Przygotowanie środowiska” (po linii 31, przed `## Jak pracujemy`) wstaw sekcję:

````markdown
## Klaster lokalny

```bash
make cluster     # kind (control-plane + 2 workery) z Cilium i Hubble; ponowne uruchomienie jest bezpieczne
make hubble-ui   # Hubble UI w przeglądarce (port-forward na localhost:12000, Ctrl+C kończy)
```

`make cluster` tworzy klaster kind `secure-k8s-aiops` i kontekst kubectl `kind-secure-k8s-aiops`. Porty 8080, 3000 i 8025 na `127.0.0.1` muszą być wolne. Usunięcie klastra: `kind delete cluster --name secure-k8s-aiops`.
````

## Critical files & anchors

- `Makefile` linie 1–3: `export PATH := $(shell mise bin-paths …)` – musi zostać pierwszą instrukcją; dzięki niej `cluster` i `hubble-ui` wołają kind/helm/cilium/kubectl w wersjach z `mise.toml`.
- `.gitignore` linie 12–13: `*.env` + `!platform/versions.env` – nie zmieniaj nazwy ani położenia pliku wersji.
- `docs/architektura.md` linie 9, 23, 36–45, 70–74: wiersz kind, akapit o wersjach, „Dostęp z hosta”, „Kontrakt metryk i logów”.
- `scripts/doctor.sh` linie 58–72: tabela narzędzi już obejmuje kind, kubectl, helm, cilium-cli i hubble – bez zmian.

## Verification

Warunki wstępne (katalog roboczy: korzeń repozytorium):
- `mise install` wykonane; Docker działa; jest dostęp do internetu (obrazy, charty OCI, testy connectivity).
- `mise exec -- kind get clusters` nie zwraca `secure-k8s-aiops`.
- `ss -ltnH '( sport = :8080 or sport = :3000 or sport = :8025 )'` nic nie wypisuje. Na maszynie R1 port `127.0.0.1:8080` zajmuje serwer llama.cpp (`curl -sI http://127.0.0.1:8080/` → `Server: llama.cpp`) – na czas weryfikacji zatrzymuje go właściciel maszyny; mapowań portów nie zmieniamy (kontrakt).

Kroki i oczekiwany wynik:
1. `make doctor` → kod 0, ostatnia linia `Wszystkie sprawdzenia przeszły.`
2. `time make cluster` → kod 0; powstaje klaster `secure-k8s-aiops`, oba release'y Helm mają `STATUS: deployed`, w podsumowaniu `cilium status` każdy komponent (agent Cilium, operator, Envoy, Hubble Relay) ma `OK` (`ClusterMesh: disabled` jest oczekiwane), na końcu trzy linie `node/secure-k8s-aiops-… condition met`. Czas zapisz do dowodu.
3. `docker port secure-k8s-aiops-control-plane` → zawiera `30080/tcp -> 127.0.0.1:8080`, `30300/tcp -> 127.0.0.1:3000`, `30825/tcp -> 127.0.0.1:8025`.
4. `mise exec -- kubectl --context kind-secure-k8s-aiops get nodes` → `secure-k8s-aiops-control-plane`, `secure-k8s-aiops-worker`, `secure-k8s-aiops-worker2`, wszystkie `Ready`, wersja `v1.36.4`.
5. Idempotencja:

```bash
mkdir -p reports
mise exec -- kubectl --context kind-secure-k8s-aiops -n kube-system get pods -o name | sort > reports/t03-pods-before.txt
make cluster
mise exec -- kubectl --context kind-secure-k8s-aiops -n kube-system get pods -o name | sort | diff reports/t03-pods-before.txt -
```

   → drugie `make cluster` wypisuje `Klaster secure-k8s-aiops już istnieje.` i kończy się kodem 0; `diff` nic nie wypisuje (żaden pod nie został odtworzony).
6. Kryterium 1: `mise exec -- cilium status --context kind-secure-k8s-aiops --wait` → kod 0; każdy komponent (agent Cilium, operator, Envoy, Hubble Relay) ma `OK`; brak sekcji `Errors`/`Warnings`.
7. Kryterium 2: `mise exec -- hubble observe --port-forward --kube-context kind-secure-k8s-aiops --last 20` → niepusta lista przepływów (np. `kube-system/coredns-…` z werdyktem `FORWARDED`).
8. Kryterium 3: `bash -o pipefail -c 'mise exec -- cilium connectivity test --context kind-secure-k8s-aiops 2>&1 | tee reports/t03-connectivity-test.log'` → kod 0; raport końcowy (`📋 Test Report`) oznacza wykonane testy jako udane (`✅ … successful`) i nie zawiera linii z `❌`; pominięte testy (`skipped`) wypisz do dowodu.
9. Kontrakt metryk (po kroku 8, przed sprzątaniem):

```bash
mise exec -- kubectl --context kind-secure-k8s-aiops -n kube-system get servicemonitors
mise exec -- kubectl --context kind-secure-k8s-aiops -n kube-system get configmap cilium-config -o jsonpath='{.data.hubble-metrics}'
for p in $(mise exec -- kubectl --context kind-secure-k8s-aiops -n kube-system get pods -l k8s-app=cilium -o name); do
  mise exec -- kubectl --context kind-secure-k8s-aiops get --raw "/api/v1/namespaces/kube-system/pods/${p#pod/}:9965/proxy/metrics"
done | grep '^hubble_drop_total{' | grep 'reason="POLICY_DENIED"'
```

   → ServiceMonitory `cilium-agent`, `cilium-operator`, `hubble`; ConfigMap: sześć linii od `dns:labelsContext=…` do `icmp:labelsContext=…`; co najmniej jedna seria `hubble_drop_total` z `reason="POLICY_DENIED"`, `destination_namespace="cilium-test-1"` oraz niepustymi `source_workload` i `destination_workload` (źródło: test `all-ingress-deny-knp`, który w cilium-cli v0.20.1 oczekuje odrzuceń `POLICY_DENIED`).
10. `make hubble-ui` uruchomione w tle → `curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:12000/` zwraca `200`; potem zatrzymaj proces.
11. Sprzątanie: `mise exec -- kubectl --context kind-secure-k8s-aiops delete $(mise exec -- kubectl --context kind-secure-k8s-aiops get ns -o name | grep '^namespace/cilium-test')` → namespace'y `cilium-test-*` usunięte; klaster zostaje.
12. Dowód: `reports/t03-dowod.md` (katalog `reports/` jest poza git) z wynikami kroków 2 (czas), 4, 6, 7, podsumowaniem kroku 8 (ostatnie 30 linii logu oraz lista pominiętych testów z powodem) i kroku 9. Komentarz w issue #3 publikuje właściciel issue (`gh issue comment 3 --body-file reports/t03-dowod.md`); wykonawca planu go nie publikuje.

## Assumptions & contingencies

Założenia (do zmiany przez właściciela):
- Nazwa klastra `secure-k8s-aiops`, kontekst `kind-secure-k8s-aiops`; T04 (`down`) używa `CLUSTER_NAME` z Makefile.
- Charty z rejestrów OCI zamiast `helm repo add`.
- Release CRD w `kube-system`, chart `prometheus-operator-crds` 32.0.1 (operator v0.94.1); kube-prometheus-stack w T16 bez CRD.
- Konflikt portu 8080 na maszynie R1 rozwiązuje zatrzymanie llama.cpp, nie zmiana kontraktu portów.

Plan awaryjny:
- `kind create cluster` kończy się błędem `address already in use` / `port is already allocated` → zwolnij port i uruchom `make cluster` ponownie; jeśli `kind get clusters` pokazuje `secure-k8s-aiops` bez działających węzłów, najpierw `mise exec -- kind delete cluster --name secure-k8s-aiops`.
- `helm upgrade` Cilium przekracza `--timeout 10m` (wolne łącze) → uruchom `make cluster` ponownie; pobrane obrazy zostają na węzłach.
- `cilium connectivity test` zgłasza błędy tylko w testach wymagających internetu → powtórz z `--test '!<nazwa-testu>'` dla każdego z nich i wpisz je do dowodu jako „pominięte: wymagają internetu”. Błędy w innych testach → nie zmieniaj values, żeby test przeszedł; powtórz z `--collect-sysdump-on-failure`, zostaw sysdump w `reports/`, zgłoś właścicielowi nazwy testów i zatrzymaj się.
- Brak serii `POLICY_DENIED` w kroku 9 → sprawdź w `reports/t03-connectivity-test.log`, czy test `all-ingress-deny-knp` się wykonał; jeśli został pominięty, zgłoś to właścicielowi; nie zmieniaj `labelsContext`.
