# secure-k8s-aiops

Bezpieczna platforma Kubernetes z obserwowalnością AI — projekt zespołowy.

Lokalny klaster kind z Cilium i Hubble, dwie usługi (frontend, orders), RBAC, NetworkPolicy, Pod Security, skan obrazów, metryki, logi i dashboardy oraz detekcja anomalii ML z alertami.

**Status:** planowanie. Kod powstaje od Sprintu 1 (zadania T02–T05).

- Karta projektu: [docs/karta-projektu.md](docs/karta-projektu.md)
- Architektura i kontrakty: [docs/architektura.md](docs/architektura.md)
- Zadania: [Issues](https://github.com/l3x1cn/secure-k8s-aiops/issues), sprinty: [Milestones](https://github.com/l3x1cn/secure-k8s-aiops/milestones)
- Tablica: [GitHub Project](https://github.com/users/l3x1cn/projects/1)

## Wymagania

- Docker z co najmniej 8 GB pamięci:
  - **Linux:** Docker Engine. Dostęp bez sudo: `sudo usermod -aG docker $USER`, potem wyloguj się i zaloguj ponownie.
  - **macOS:** Docker Desktop z co najmniej 8 GB RAM (Settings → Resources).
  - **Windows:** WSL2 z dystrybucją Linuksa (np. Ubuntu) i Docker Desktop z backendem WSL2. Pamięć dla WSL2 ustawia `memory=8GB` (lub więcej) w sekcji `[wsl2]` pliku `%UserProfile%\.wslconfig`. Repozytorium klonuj i wszystkie polecenia uruchamiaj w WSL.
- Linux i WSL2: limity inotify dla kind: `fs.inotify.max_user_watches` ≥ 524288, `fs.inotify.max_user_instances` ≥ 512. `make doctor` podaje polecenie naprawy.
- [mise](https://mise.jdx.dev/getting-started.html) 2026.10.13 lub nowsze, git, GNU make, bash.

## Przygotowanie środowiska

```bash
mise install   # narzędzia w wersjach z mise.toml
make doctor    # narzędzia, Docker bez sudo, pamięć Dockera, limity inotify
uv sync        # Python 3.13 i zależności w .venv
```

`make` używa narzędzi z `mise.toml` także bez aktywacji mise w powłoce. Poza `make` (np. `kubectl`, `uv sync`) aktywuj mise według [instrukcji](https://mise.jdx.dev/getting-started.html) albo poprzedzaj polecenia `mise exec --`.

## Usługi

`frontend` i `orders` (FastAPI) słuchają na porcie 8080 i wymagają zmiennej `ORDERS_API_TOKEN`. Wspólny kod metryk i logów jest w `libs/observability`.

```bash
uv run pytest                                         # testy jednostkowe usług
docker build -f services/orders/Dockerfile -t ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev .
ORDERS_API_TOKEN=dev uv run python -m frontend        # uruchomienie lokalne
```

Manifesty są w `deploy/base/{frontend,orders,fault-runner}`; tag obrazu ustawia overlay.

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
- Wspólne kontrakty (porty, nazwy metryk, alerty, sekrety, scenariusze) zmieniamy tylko PR-em do `docs/architektura.md`.
