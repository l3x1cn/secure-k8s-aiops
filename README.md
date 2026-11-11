# secure-k8s-aiops

Bezpieczna platforma Kubernetes z obserwowalnością AI — projekt zespołowy.

Lokalny klaster kind z Cilium i Hubble, dwie usługi (frontend, orders), RBAC, NetworkPolicy, Pod Security, skan obrazów, metryki, logi i dashboardy oraz detekcja anomalii ML z alertami.

**Status:** planowanie. Kod powstaje od Sprintu 1 (zadania T02–T05).

- Karta projektu: [docs/karta-projektu.md](docs/karta-projektu.md)
- Architektura i kontrakty: [docs/architektura.md](docs/architektura.md)
- Model zagrożeń i macierz kontroli: [docs/bezpieczenstwo.md](docs/bezpieczenstwo.md)
- Detekcja anomalii (metoda, próg, wyniki prototypu): [docs/detekcja.md](docs/detekcja.md)
- Zadania: [Issues](https://github.com/l3x1cn/secure-k8s-aiops/issues), sprinty: [Milestones](https://github.com/l3x1cn/secure-k8s-aiops/milestones)
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
make up      # cała platforma: kind z Cilium i Hubble, namespace'y, sekrety, Prometheus i Grafana, obrazy :dev, aplikacje
make status  # węzły, release'y Helm i pody
make urls    # adresy usług na hoście
make down    # usuwa klaster razem ze wszystkim, co w nim działa
```

`make up` od zera trwa ok. 4 min (maszyna R3: 4 CPU, 7 GB RAM, obrazy bazowe w cache Dockera, obrazy kube-prometheus-stack pobierane do węzłów; przed T16 na maszynie R1 ok. 3 min). Ponowne `make up` na działającym klastrze niczego nie zmienia. Klaster kind `secure-k8s-aiops` ma kontekst kubectl `kind-secure-k8s-aiops`. Porty 8080, 3000 i 8025 na `127.0.0.1` muszą być wolne. Frontend: http://localhost:8080.

Kroki `make up` w tej kolejności; każdy działa też osobno:

```bash
make cluster        # kind (control-plane + 2 workery) z Cilium i Hubble
make secrets        # namespace'y i brakujące sekrety; wartości nie trafiają na dysk ani na ekran
make observability  # kube-prometheus-stack w monitoring (najpierw make secrets): Prometheus, Alertmanager, Grafana
make images         # obrazy :dev frontend, orders i fault-runner, załadowane do kind
make deploy         # overlay deploy/overlays/local (z ServiceMonitorami i regułami); czeka na gotowość Deploymentów
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

Testy na działającym klastrze (kubectl, kustomize i hubble z mise w PATH; `make test-security` dojdzie w T26, `make test` w T27); `tests/security/test_secrets.py` działa też bez klastra:

```bash
uv run --locked pytest tests/security       # RBAC (T11), NetworkPolicy (T12), Pod Security (T13), sekrety (T14): konta usług, role zespołu, przepływy, odrzucenie poda uprzywilejowanego, securityContext podów, brak wartości sekretów w deploy/, gitleaks na historii HEAD
uv run --locked pytest tests/observability  # metryki (T16): cele aplikacji, Hubble, reguły service:* (ok. 1 min, ruch z fault-runner spike); ruch Locust (T18): okres ok. 30 min, pomijany przez pierwsze 65 min Locusta
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

## Jak pracujemy

- Każde zadanie to issue `Txx`. Gałąź `txx-krotki-opis`, PR z `Closes #N`.
- PR wymaga zielonego CI i jednej recenzji (od T06).
- Przed PR: `make lint unit gitleaks manifests` (te same kontrole co CI).
- Obrazy: PR je buduje (wymagana kontrola `images`), a push na `main` publikuje `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:sha-<7 znaków SHA commita>` ([docs/architektura.md](docs/architektura.md#obrazy)).
- Wspólne kontrakty (porty, nazwy metryk, alerty, sekrety, scenariusze) zmieniamy tylko PR-em do `docs/architektura.md`.
