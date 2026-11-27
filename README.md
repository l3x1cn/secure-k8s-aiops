# secure-k8s-aiops

Bezpieczna platforma Kubernetes z obserwowalnością AI — projekt zespołowy.

Lokalny klaster kind z Cilium i Hubble, dwie usługi (frontend, orders), RBAC, NetworkPolicy, Pod Security, skan obrazów, metryki, logi i dashboardy oraz detekcja anomalii ML z alertami.

**Status:** zamknięte 20 z 36 zadań (platforma, bezpieczeństwo, metryki, logi); w toku eksport cech dla detektora (T20). Szczegóły: [docs/backlog.md](docs/backlog.md).

- Karta projektu: [docs/karta-projektu.md](docs/karta-projektu.md)
- Architektura i kontrakty (z diagramem): [docs/architektura.md](docs/architektura.md#diagram)
- Model zagrożeń i macierz kontroli: [docs/bezpieczenstwo.md](docs/bezpieczenstwo.md)
- Detekcja anomalii (metoda, próg, wyniki prototypu): [docs/detekcja.md](docs/detekcja.md)
- Zadania: [Issues](https://github.com/l3x1cn/secure-k8s-aiops/issues), sprinty: [Milestones](https://github.com/l3x1cn/secure-k8s-aiops/milestones)
- Backlog (migawka Issues według sprintów): [docs/backlog.md](docs/backlog.md)
- Tablica: [GitHub Project](https://github.com/users/l3x1cn/projects/1)

## Wymagania

- Docker z co najmniej 8 GB pamięci:
  - **Linux:** Docker Engine. Dostęp bez sudo: `sudo usermod -aG docker $USER`, potem wyloguj się i zaloguj ponownie. `make images` wymaga Docker Buildx: pakiet `docker-buildx` (Arch, Ubuntu) albo `docker-buildx-plugin` (repozytorium Dockera).
  - **macOS:** Docker Desktop z co najmniej 8 GB RAM (Settings → Resources).
  - **Windows:** WSL2 z dystrybucją Linuksa (np. Ubuntu) i Docker Desktop z backendem WSL2. Pamięć dla WSL2 ustawia `memory=8GB` (lub więcej) w sekcji `[wsl2]` pliku `%UserProfile%\.wslconfig`. Repozytorium klonuj i wszystkie polecenia uruchamiaj w WSL.
- Linux i WSL2: limity inotify dla kind: `fs.inotify.max_user_watches` ≥ 524288, `fs.inotify.max_user_instances` ≥ 512. `make doctor` podaje polecenie naprawy.
- [mise](https://mise.jdx.dev/getting-started.html) 2026.10.25 lub nowsze, git, GNU make, bash, openssl.

## Przygotowanie środowiska

```bash
mise install                  # narzędzia w wersjach z mise.toml
make doctor                   # narzędzia, Docker bez sudo, pamięć Dockera, Docker Buildx, openssl, limity inotify
uv sync                       # Python 3.13 i zależności w .venv
uvx pre-commit@4.7.0 install  # hook gitleaks przed commitem (T14), raz po klonie
```

`make` używa narzędzi z `mise.toml` także bez aktywacji mise w powłoce. Poza `make` (np. `kubectl`, `uv sync`) aktywuj mise według [instrukcji](https://mise.jdx.dev/getting-started.html) albo poprzedzaj polecenia `mise exec --`.

Hook z `.pre-commit-config.yaml` przy każdym commicie uruchamia gitleaksa z `mise.toml` (`mise exec`) na zmianach w indeksie. Gdy znajdzie sekret, commit nie powstaje, a log pokazuje plik, linię i regułę z wartością `REDACTED`. Commit wymaga więc `mise` w PATH. Skrypt hooka wskazuje Pythona z cache uv: po `uv cache clean` hook kończy się błędem „`pre-commit` not found” i blokuje commit; wtedy powtórz `uvx pre-commit@4.7.0 install`. Całą historię i tak skanuje job CI `secrets` (`make gitleaks`).

## Klaster lokalny

```bash
make up      # cała platforma: kind z Cilium i Hubble, namespace'y, sekrety, Prometheus, Grafana, Loki i Alloy, obrazy :dev, aplikacje
make status  # węzły, release'y Helm i pody
make urls    # adresy usług na hoście
make down    # usuwa klaster razem ze wszystkim, co w nim działa
```

`make up` od zera trwa ok. 4 min (maszyna R3: 4 CPU, 7 GB RAM, obrazy bazowe w cache Dockera, obrazy kube-prometheus-stack pobierane do węzłów; przed T16 na maszynie R1 ok. 3 min). Ponowne `make up` na działającym klastrze niczego nie zmienia. Klaster kind `secure-k8s-aiops` ma kontekst kubectl `kind-secure-k8s-aiops`. Porty 8080, 3000 i 8025 na `127.0.0.1` muszą być wolne. Frontend: http://localhost:8080.

Kroki `make up` w tej kolejności; każdy działa też osobno:

```bash
make cluster        # kind (control-plane + 2 workery) z Cilium i Hubble
make secrets        # namespace'y i brakujące sekrety; wartości nie trafiają na dysk ani na ekran
make observability  # w monitoring (najpierw make secrets): kube-prometheus-stack (Prometheus, Alertmanager, Grafana), Loki i Alloy
make images         # obrazy :dev frontend, orders i fault-runner, załadowane do kind
make deploy         # overlay deploy/overlays/local (z ServiceMonitorami, regułami i Mailpit); czeka na gotowość Deploymentów
```

Grafana: http://localhost:3000, użytkownik `admin`, hasło wypisuje `make grafana-password` (losowe, z Secretu `monitoring/grafana-admin`, który tworzy `make secrets`).

Tag `:dev` się nie zmienia, więc po zmianie kodu usługi: `make images`, potem `kubectl -n <namespace> rollout restart deployment/<nazwa>`.

Port-forward (Ctrl+C kończy):

```bash
make hubble-ui     # Hubble UI: http://localhost:12000
make hubble-relay  # Hubble Relay na localhost:4245; w drugim terminalu: hubble observe --last 20
make prometheus    # Prometheus (od T16): http://localhost:9090
make alertmanager  # Alertmanager (od T16): http://localhost:9093
```

Testy na działającym klastrze (`make test-security` i `tests/security/mutation_check.sh` same biorą narzędzia z mise; `uv run … pytest` potrzebuje kubectl, kustomize i hubble z mise w PATH; `make test` dojdzie w T27); `tests/security/test_secrets.py` działa też bez klastra:

```bash
make test-security                          # testy z markerem security: RBAC (T11), NetworkPolicy (T12, T26), Pod Security (T13), sekrety (T14); wyniki w reports/junit-security.xml i reports/security.html
bash tests/security/mutation_check.sh       # test mutacyjny (T26, ok. 3–4 min): bez shop/default-deny musi paść test poda bez reguły; polityka wraca na końcu, logi w reports/mutation-check/
uv run --locked pytest tests/security       # te same testy bez raportów: konta usług, role zespołu, przepływy, pod bez reguły, odrzucenie poda uprzywilejowanego, securityContext podów, brak wartości sekretów w deploy/, gitleaks na historii HEAD
uv run --locked pytest tests/observability  # metryki (T16): cele aplikacji, Hubble, reguły service:* (ok. 1 min, ruch z fault-runner spike); logi i zdarzenia (T17): źródło Loki w Grafanie, ERROR orders po fault errors, BackOff po dwóch fault crash (ok. 1 min; orders restartuje się dwa razy, e-mail PodRestarts); ruch Locust (T18): okres ok. 30 min, pomijany przez pierwsze 65 min Locusta
```

## Usługi

`frontend` i `orders` (FastAPI) słuchają na porcie 8080 i wymagają zmiennej `ORDERS_API_TOKEN`. Wspólny kod metryk i logów jest w `libs/observability`.

```bash
uv run pytest                                         # testy jednostkowe usług
docker build -f services/orders/Dockerfile -t ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev .
ORDERS_API_TOKEN=dev uv run python -m frontend        # uruchomienie lokalne
```

Manifesty są w `deploy/base/{frontend,orders,fault-runner,locust,intruder}`, konta usług i role zespołu (RBAC) w `deploy/base/rbac`, a NetworkPolicy w `deploy/base/networkpolicies`; tag obrazów budowanych w projekcie ustawia overlay. Do klastra obrazy `:dev` buduje i ładuje `make images` (krok `make up`).

### Ruch (Locust)

`make deploy` uruchamia w loadgen Locusta bez interfejsu WWW. Ruch do frontendu rośnie i maleje z okresem 30 min (2–18 użytkowników, 70% `GET /`, 30% `POST /order`; szczegóły w [docs/architektura.md](docs/architektura.md#ruch-locust)). Profil jest w `deploy/base/locust/locustfile.py`; po zmianie wystarczy `make deploy`.

```bash
kubectl -n loadgen logs deploy/locust   # zmiany liczby użytkowników
```

W Prometheusie albo w Grafanie (Explore): `service:http_requests:rate1m{service="frontend"}`.

### Awarie (fault-runner)

`orders` przy `FAULTS_ENABLED=true` i `FAULT_TOKEN` udostępnia `/faults/*` (scenariusze S1–S5 w [docs/architektura.md](docs/architektura.md#scenariusze-awarii)). Klient `fault-runner` działa jako pod w namespace `loadgen`:

```bash
docker build -f chaos/Dockerfile -t ghcr.io/l3x1cn/secure-k8s-aiops/fault-runner:dev .
FR="kubectl -n loadgen exec deploy/fault-runner -- fault-runner"
$FR fault errors --seconds 180 --param ratio=0.5   # S3
$FR fault memory --param target_ratio=0.9          # S2, domyślnie 180 s
$FR stop                                           # koniec bieżącej awarii
$FR spike --users 50 --seconds 180                 # S6: skok ruchu na frontend
```

### Scenariusze awarii (chaos/run.py)

Orkiestrator uruchamia scenariusze S1–S7 przez `kubectl exec` w `loadgen/fault-runner` i `intruder/intruder` i zapisuje ich okna (etykiety prawdy do ewaluacji detekcji) w `reports/runs/<run-id>/` (poza git). Kontrakt: [docs/architektura.md](docs/architektura.md#scenariusze-awarii).

```bash
uv run --locked python chaos/run.py                                    # S1–S7, przerwa 10 min: ok. 1 h 41 min
uv run --locked python chaos/run.py --scenarios S1,S3,S7 --gap 4m --run-id e2e
cat reports/runs/e2e/labels.jsonl reports/runs/e2e/run.json            # okna i commit przebiegu
```

Przerwa `--gap` trwa przed każdym scenariuszem i po ostatnim. Każde okno dostaje w Grafanie adnotację z tagiem `scenario`; dashboard pokazuje ją zapytaniem adnotacji ze źródłem `-- Grafana --` i filtrem po tagu `scenario` (ustawienia dashboardu → Annotations). Ctrl+C zatrzymuje bieżący scenariusz (`fault-runner stop`, w S6 i S7 także proces w podzie), zamyka jego okno i kończy przebieg kodem 130.

### Alerty (Mailpit)

Alertmanager wysyła każdy alert e-mailem do Mailpit: http://localhost:8025 (UI, NodePort 30825). Alerty regułowe są w `deploy/observability/alert-rules.yaml`, a routing w `alertmanager.config` w `deploy/observability/values/kube-prometheus-stack.yaml` (zmiana: `make observability`). Opis i progi: [docs/architektura.md](docs/architektura.md#alerty).

```bash
# PolicyDeniedConnections: 2 min prób intruder → orders; e-mail po ok. 2 min
kubectl -n intruder exec deploy/intruder -- sh -c 'end=$(($(date +%s)+120)); while [ $(date +%s) -lt $end ]; do curl -s -o /dev/null -m 1 http://orders.shop.svc:8080/healthz; sleep 1; done'
# HighErrorRate: S3; wymaga ruchu HTTP (Locust z T18 albo fault-runner spike); e-mail po ok. 3–4 min
kubectl -n loadgen exec deploy/fault-runner -- fault-runner fault errors --seconds 180 --param ratio=0.5
curl -s 'localhost:8025/api/v1/search?query=subject:HighErrorRate'   # e-maile przez API Mailpit
```

### Logi i zdarzenia (Loki)

Grafana Alloy (DaemonSet w monitoring) wysyła do Lokiego logi kontenerów i zdarzenia Kubernetes z shop, loadgen, aiops i intruder; Loki trzyma je 72 h. Przegląd w Grafanie: Explore, źródło Loki. Etykiety i pola: [docs/architektura.md](docs/architektura.md#kontrakt-metryk-i-logów).

- `{namespace="shop", container="orders"} | json | level="ERROR"`: błędy orders, np. po S3 (`fault errors`);
- `{job="loki.source.kubernetes_events", namespace="shop"} | json | type="Warning"`: zdarzenia Warning, np. `BackOff` po drugim `fault crash` w ciągu 10 min.

### Dane i cechy (aiops)

Pakiet `aiops` pobiera z Prometheusa 9 cech z reguł nagrywających `service:*` dla `frontend` i `orders` co 30 s i zapisuje je do Parquet w `aiops/data/` (poza git). Kontrakt ramki: [docs/architektura.md](docs/architektura.md#kontrakt-metryk-i-logów).

```bash
make prometheus   # drugi terminal: Prometheus na localhost:9090
uv run python -m aiops.export --from 2026-11-23T08:00:00Z --to 2026-11-23T10:00:00Z --out aiops/data/baseline.parquet
uv run jupyter nbconvert --to notebook --execute --inplace aiops/notebooks/02-eda.ipynb   # EDA (T20) na aiops/data/baseline.parquet, co najmniej 2 h ruchu
```

Eksport wypisuje JSON z zakresem, liczbą kroków na usługę, liczbą cech i najdłuższą luką (`max_gap_seconds`, w sekundach). Bez ruchu HTTP cechy `http_*` mają 0, a brak ewaluacji pozostałych reguł to NaN. Inny adres Prometheusa: `--prometheus-url`. Testy pakietu (`aiops/tests`, nagrane odpowiedzi Prometheusa) uruchamia `make unit`.

## Jak pracujemy

- Każde zadanie to issue `Txx`. Gałąź `txx-krotki-opis`, PR z `Closes #N`.
- PR wymaga zielonego CI i jednej recenzji (od T06).
- Przed PR: `make lint unit gitleaks manifests trivy-config` (te same kontrole co CI).
- Obrazy: PR je buduje (wymagana kontrola `images`), a push na `main` publikuje `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:sha-<7 znaków SHA commita>` ([docs/architektura.md](docs/architektura.md#obrazy)).
- Wspólne kontrakty (porty, nazwy metryk, alerty, sekrety, scenariusze) zmieniamy tylko PR-em do `docs/architektura.md`.
