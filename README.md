# secure-k8s-aiops

Bezpieczna platforma Kubernetes z obserwowalnością AI — projekt zespołowy.

Lokalny klaster kind z Cilium i Hubble, dwie usługi (frontend, orders), RBAC, NetworkPolicy, Pod Security, skan obrazów, metryki, logi i dashboardy oraz detekcja anomalii ML z alertami.

**Status:** planowanie. Kod powstaje od Sprintu 1 (zadania T02–T05).

- Karta projektu: [docs/karta-projektu.md](docs/karta-projektu.md)
- Architektura i kontrakty: [docs/architektura.md](docs/architektura.md)
- Zadania: [Issues](https://github.com/l3x1cn/secure-k8s-aiops/issues), sprinty: [Milestones](https://github.com/l3x1cn/secure-k8s-aiops/milestones)

## Jak pracujemy

- Każde zadanie to issue `Txx`. Gałąź `txx-krotki-opis`, PR z `Closes #N`.
- PR wymaga zielonego CI i jednej recenzji (od T06).
- Wspólne kontrakty (porty, nazwy metryk, alerty, sekrety, scenariusze) zmieniamy tylko PR-em do `docs/architektura.md`.
