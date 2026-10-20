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

## Klaster lokalny

```bash
make cluster     # kind (control-plane + 2 workery) z Cilium i Hubble; ponowne uruchomienie jest bezpieczne
make hubble-ui   # Hubble UI w przeglądarce (port-forward na localhost:12000, Ctrl+C kończy)
```

`make cluster` tworzy klaster kind `secure-k8s-aiops` i kontekst kubectl `kind-secure-k8s-aiops`. Porty 8080, 3000 i 8025 na `127.0.0.1` muszą być wolne. Usunięcie klastra: `kind delete cluster --name secure-k8s-aiops`.

## Jak pracujemy

- Każde zadanie to issue `Txx`. Gałąź `txx-krotki-opis`, PR z `Closes #N`.
- PR wymaga zielonego CI i jednej recenzji (od T06).
- Wspólne kontrakty (porty, nazwy metryk, alerty, sekrety, scenariusze) zmieniamy tylko PR-em do `docs/architektura.md`.
