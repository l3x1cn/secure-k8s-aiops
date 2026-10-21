# Architektura i kontrakty

Ten dokument to wspólny kontrakt dla zadań T01–T36. Zmiana kontraktu wymaga PR, który aktualizuje ten plik i opis zadań, których dotyczy.

## Komponenty i wersje

| Komponent | Wersja | Namespace | Zadanie |
|---|---|---|---|
| kind, obraz węzła `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed` | 0.33.0 | — | T03 |
| Cilium + Hubble (relay, UI, metryki) | 1.20.3 | kube-system | T03 |
| prometheus-operator-crds | przypięta w `platform/versions.env` | — | T03 |
| kube-prometheus-stack (Prometheus, Alertmanager, Grafana) | przypięta w `versions.env` | monitoring | T16 |
| Loki (chart z `grafana-community/helm-charts`, SingleBinary) | przypięta w `versions.env` | monitoring | T17 |
| Grafana Alloy | przypięta w `versions.env` | monitoring | T17 |
| Mailpit | przypięta po digest | monitoring | T19 |
| frontend, orders (Python 3.13, FastAPI) | — | shop | T05 |
| locust, fault-runner | — | loadgen | T18, T08 |
| anomaly-detector (scikit-learn) | — | aiops | T24 |
| intruder (`curlimages/curl`) | przypięta po digest | intruder | T12 |

Narzędzia CLI w `mise.toml` (T02): Python 3.13.16, kind 0.33.0, kubectl 1.37.1, helm 4.3.1, kustomize 5.8.3, cilium-cli 0.20.1, hubble 1.20.2 (`github:cilium/hubble`), trivy 0.76.0, gitleaks 8.30.1, kubeconform 0.8.0, promtool 3.15.0, uv 0.13.1; opentofu 1.13.1 dla rozszerzenia T33.

Wersje oznaczone „przypięta” wybiera się w dniu realizacji zadania (najnowsza stabilna) i wpisuje do `platform/versions.env`. Trivy nigdy w wersji 0.69.4 (złośliwe wydanie, CVE-2026-33634). Charty Helm z rejestrów OCI przypina się wersją i digestem manifestu (`*_CHART_DIGEST` w `platform/versions.env`): `make cluster` instaluje `<chart>@<digest>` z `--version`, a Helm przerywa instalację, gdy tag wersji wskazuje inny digest.

Kubernetes 1.36 zamiast 1.37 to świadomy downgrade o jedną wersję (T03). kind 0.33.0 domyślnie stawia Kubernetes 1.37.0, ale Cilium 1.20 deklaruje testy e2e tylko dla Kubernetes 1.33–1.36 ([wymagania Cilium 1.20](https://docs.cilium.io/en/v1.20/network/kubernetes/requirements/)), więc węzły używają obrazu `kindest/node:v1.36.4`, zbudowanego dla kind 0.33.0. kubectl 1.37.1 z `mise.toml` zostaje, bo odchylenie o jedną wersję jest dozwolone. Na 1.37 przechodzimy, gdy przypięta wersja Cilium obejmie ją testami.

## Namespace'y i Pod Security

| Namespace | Zawartość | PSA `enforce` |
|---|---|---|
| shop | frontend, orders | restricted |
| loadgen | locust, fault-runner | restricted |
| aiops | anomaly-detector | restricted |
| intruder | intruder | restricted |
| monitoring | kube-prometheus-stack, Loki, Alloy, Mailpit | privileged; wyjątek: node-exporter i Alloy potrzebują dostępu do hosta |
| kube-system | Cilium, Hubble, CoreDNS | bez zmian |

## Dostęp z hosta

Klaster kind `secure-k8s-aiops` (kontekst kubectl `kind-secure-k8s-aiops`) tworzy `make cluster` (T03).

Nie ma kontrolera Ingress (Ingress NGINX wycofano w marcu 2026); w demo wystarcza NodePort. Mapowania `extraPortMappings` w kind nasłuchują tylko na `127.0.0.1`.

| Adres | Usługa | Mechanizm |
|---|---|---|
| http://localhost:8080 | frontend | NodePort 30080 |
| http://localhost:3000 | Grafana | NodePort 30300 |
| http://localhost:8025 | Mailpit UI | NodePort 30825 |
| `make hubble-ui`, `make hubble-relay`, `make prometheus`, `make alertmanager` | Hubble UI, Hubble CLI (relay, localhost:4245), Prometheus, Alertmanager | port-forward |

## Przepływy sieciowe

Wszystkie kontenery aplikacyjne słuchają na porcie 8080 (HTTP, `/metrics`, `/healthz`). W namespace'ach shop, loadgen i aiops obowiązuje default-deny dla ruchu przychodzącego i wychodzącego. Dozwolone są tylko te przepływy:

| Źródło | Cel | Port | Po co |
|---|---|---|---|
| dowolne | shop/frontend | 8080 | publiczna usługa (NodePort, Locust, fault-runner, intruder) |
| shop/frontend | shop/orders | 8080 | API zamówień |
| loadgen/fault-runner | shop/orders | 8080 | wstrzykiwanie awarii (z tokenem) |
| loadgen/locust, loadgen/fault-runner | shop/frontend | 8080 | ruch i skok ruchu |
| monitoring/Prometheus | shop/*, aiops/* | 8080 | pobieranie `/metrics` |
| aiops/anomaly-detector | monitoring/Prometheus :9090, monitoring/Loki :3100 | — | cechy i kontekst zdarzeń |
| każdy pod w shop, loadgen, aiops | kube-system/kube-dns | 53 UDP/TCP | DNS |

Testy (T12) sprawdzają, że te przepływy są odrzucane:
- intruder → orders
- orders → frontend
- orders → internet
- frontend → internet
- fault-runner → internet

Używamy wyłącznie `networking.k8s.io/v1` NetworkPolicy, żeby te same manifesty działały w chmurze (T29).

W kube-system NetworkPolicy `hubble-relay-ui-ingress` (T03, `platform/cilium/hubble-networkpolicy.yaml`, stosuje ją `make cluster`) dopuszcza do Hubble Relay tylko ruch z Hubble UI na porcie 4245, a do Hubble UI nie dopuszcza ruchu z podów. Dostęp z hosta zostaje przez port-forward (`make hubble-ui`, `make hubble-relay`). Nowy klient Hubble Relay w klastrze wymaga reguły w tej polityce. Agent i operator Cilium działają w sieci hosta, więc NetworkPolicy ich nie obejmuje: metryki na portach 9962, 9963 i 9965 są czytelne z każdego poda (ryzyko szczątkowe, T07).

## Kontrakt metryk i logów

- **Aplikacje.** `http_requests_total{method,route,status}`, histogram `http_request_duration_seconds` i domyślne metryki procesu z `prometheus_client`. ServiceMonitor nadaje etykiety `namespace` i `service`.
- **Logi.** Jedna linia JSON na zdarzenie, pola: `ts`, `level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`), `service`, `route`, `status`, `duration_ms`, `msg`.
- **Cilium i Hubble (T03).** CRD prometheus-operator instaluje T03 (chart `prometheus-operator-crds`, wersja w `platform/versions.env`), więc kube-prometheus-stack (T16) instaluje się bez CRD. ServiceMonitory w `kube-system`, bez dodatkowych etykiet: `cilium-agent` (port 9962), `cilium-operator` (9963) i `hubble` (9965); Prometheus (T16) wybiera ServiceMonitory ze wszystkich namespace'ów, bez filtra etykiet. Metryki Hubble `dns`, `drop`, `tcp`, `flow`, `port-distribution` i `icmp` mają etykiety `source_namespace`, `source_workload`, `destination_namespace` i `destination_workload` (puste, gdy końcem przepływu nie jest pod). Odrzucenia przez NetworkPolicy to `hubble_drop_total{reason="POLICY_DENIED"}`.
- **Reguły nagrywające (T16).** Etykieta `service` ∈ {frontend, orders}, krok 30 s. To jedyne wejście dla alertów regułowych i cech ML:

| Reguła | Znaczenie |
|---|---|
| `service:cpu_usage_ratio_of_limit` | zużycie CPU / limit CPU |
| `service:memory_working_set_ratio_of_limit` | working set pamięci / limit pamięci |
| `service:network_rx_bytes:rate1m` | ruch przychodzący poda (B/s) |
| `service:network_tx_bytes:rate1m` | ruch wychodzący poda (B/s) |
| `service:http_requests:rate1m` | żądania na sekundę |
| `service:http_errors_ratio:rate1m` | udział odpowiedzi 5xx |
| `service:http_latency_p95_seconds:1m` | p95 czasu odpowiedzi |
| `service:restarts:increase5m` | przyrost restartów kontenera w 5 min |
| `service:policy_drops:rate1m` | odrzucenia `POLICY_DENIED`, w których usługa jest celem lub źródłem (Hubble) |

- **Detektor (T24).**

| Metryka | Typ | Znaczenie |
|---|---|---|
| `aiops_anomaly_score{service}` | gauge | wynik, większy = bardziej anomalny |
| `aiops_anomaly_threshold{service}` | gauge | aktualny próg |
| `aiops_anomaly{service}` | gauge | 1 = anomalia |
| `aiops_model_ready{service}` | gauge | 1 = model wytrenowany |
| `aiops_scoring_errors_total` | counter | błędy pobierania lub oceny |

## Alerty

| Alert | Detektor | Warunek | `for` | Etykiety |
|---|---|---|---|---|
| HighCPU | rules | `service:cpu_usage_ratio_of_limit > 0.8` | 2m | `detector=rules`, `severity=warning` |
| HighMemory | rules | `service:memory_working_set_ratio_of_limit > 0.85` | 2m | jw. |
| HighErrorRate | rules | `service:http_errors_ratio:rate1m > 0.05` | 2m | jw. |
| HighLatency | rules | `service:http_latency_p95_seconds:1m > 0.3` | 2m | jw. |
| PodRestarts | rules | `service:restarts:increase5m > 0` | 0m | jw. |
| PolicyDeniedConnections | rules (Hubble) | `service:policy_drops:rate1m > 0` | 1m | jw. |
| AnomalyDetected | ml | `aiops_anomaly == 1` | 1m | `detector=ml`, `severity=warning` |
| IncidentConfirmed | hybrid | `aiops_anomaly == 1` i aktywny alert `detector="rules"` dla tego samego `service` | 0m | `detector=hybrid`, `severity=critical` |

Odbiorca: Alertmanager → Mailpit (SMTP `mailpit.monitoring.svc:1025`).

## Sekrety

Sekrety tworzy `make secrets` (T14) i nigdy nie trafiają do git.

| Secret | Namespace | Klucze | Użycie |
|---|---|---|---|
| `orders-api-token` | shop | `token` | frontend → orders (`Authorization: Bearer`) |
| `fault-token` | shop, loadgen | `token` (ta sama wartość) | fault-runner → orders (`X-Fault-Token`) |
| `grafana-admin` | monitoring | `admin-user`, `admin-password` | logowanie do Grafany |

## Scenariusze awarii

Wszystkie endpointy `/faults/*` należą do `orders`, są aktywne tylko przy `FAULTS_ENABLED=true` (overlay `local`) i wymagają nagłówka `X-Fault-Token`. `POST /faults/stop` kończy bieżącą awarię.

| ID | Nazwa | Cel | Mechanizm | Czas | Oczekiwane alerty |
|---|---|---|---|---|---|
| S1 | cpu | orders | `POST /faults/cpu?seconds=120`: pętla obciążająca CPU | 2 min | HighCPU, AnomalyDetected |
| S2 | memory | orders | `POST /faults/memory?seconds=180&target_ratio=0.9`: alokacja do 90% limitu pamięci (odczyt z cgroup) | 3 min | HighMemory, AnomalyDetected |
| S3 | errors | orders | `POST /faults/errors?seconds=180&ratio=0.5`: 50% odpowiedzi 500 | 3 min | HighErrorRate, AnomalyDetected, IncidentConfirmed |
| S4 | latency | orders | `POST /faults/latency?seconds=180&ms=500` | 3 min | HighLatency, AnomalyDetected |
| S5 | crash | orders | `POST /faults/crash` 3 razy co 60 s | 3 min | PodRestarts, AnomalyDetected |
| S6 | spike | frontend | `fault-runner spike --users 50 --seconds 180` | 3 min | AnomalyDetected (reguły nie mają progu na skok ruchu) |
| S7 | scan | orders | intruder: `curl -m 1` na orders:8080 oraz porty 22, 80, 443, 5432 i 6379, co 1 s | 2 min | PolicyDeniedConnections, AnomalyDetected |

## Struktura repozytorium

```
.
├── mise.toml              # wersje narzędzi (T02)
├── Makefile               # doctor (T02); up, down, images, secrets, test, report (T04 i dalej)
├── pyproject.toml         # uv workspace, Python 3.13 (T02)
├── platform/              # kind, Cilium, versions.env (T03, T04)
├── deploy/
│   ├── base/              # namespace'y, aplikacje, RBAC, NetworkPolicy (T04, T11–T13)
│   ├── overlays/local/    # kind (T04)
│   ├── overlays/cloud/    # zarządzany Kubernetes (T29)
│   └── observability/     # values chartów, reguły, dashboardy (T16–T19, T22)
├── services/
│   ├── frontend/          # (T05)
│   └── orders/            # (T05, T08)
├── aiops/                 # pakiet aiops: cechy, model, detektor, ewaluacja (T20–T25, T30)
├── chaos/                 # fault-runner i run.py (T08, T21)
├── tests/                 # security/, observability/, e2e/ (T11–T14, T26, T27)
├── scripts/               # doctor.sh (T02), secrets.sh (T14) i skrypty pomocnicze
├── infra/                 # OpenTofu, rozszerzenie (T33)
├── reports/               # wyniki testów i przebiegów, poza git (T26–T31)
└── docs/                  # karta, architektura, bezpieczeństwo, detekcja, runbook, demo
```
