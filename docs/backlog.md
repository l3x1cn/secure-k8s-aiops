# Backlog

Zestawienie zadań T01–T36 na 27.11.2026 (`main` po T17, T20 i T26; T21 w PR #75). Źródłem prawdy są [Issues](https://github.com/l3x1cn/secure-k8s-aiops/issues) i [Milestones](https://github.com/l3x1cn/secure-k8s-aiops/milestones) — ten plik to migawka na potrzeby przeglądu. Kontrakty zadań opisuje [architektura](architektura.md), plan sprintów i definicja ukończenia — [karta projektu](karta-projektu.md#plan-sprintów).

Legenda: **KO** — zadanie dostarcza dowód dla kryterium odbioru z karty projektu; **MVP** albo **rozszerzenie** — zakres według karty; kolumna „Zależy od” to kolejność prac (zadanie nie startuje przed zamknięciem zależności).

## Podsumowanie

- Zamknięte: 21 z 36 zadań, w tym 21 z 32 zadań MVP.
- W toku: T21 (PR #75). Zostały: Sprint 3 — T22–T25, T27–T29; Sprint 4 — T30–T36.

| Sprint | Zamknięte | Razem |
|---|---|---|
| Sprint 1 — Fundament | 9 | 9 |
| Sprint 2 — Bezpieczeństwo i obserwowalność | 11 | 12 |
| Sprint 3 — Detekcja AI i alerty | 1 | 8 |
| Sprint 4 — Raport, demo, rozszerzenia | 0 | 7 |

## Sprint 1 — Fundament

| Zadanie | Cel | Rola | Zależy od | Zakres | KO | Stan |
|---|---|---|---|---|---|---|
| [T01](https://github.com/l3x1cn/secure-k8s-aiops/issues/1) Karta zgłoszenia i organizacja zespołu | Karta projektu jest złożona, a zespół ma ustalony sposób pracy. | R1 Platforma (koordynuje, wszyscy uczestniczą) | — | MVP |  | zamknięte |
| [T02](https://github.com/l3x1cn/secure-k8s-aiops/issues/2) Środowisko deweloperskie: mise, make doctor, struktura repo | Każdy członek zespołu ma te same wersje narzędzi i może uruchomić projekt. | R1 Platforma | — | MVP |  | zamknięte |
| [T03](https://github.com/l3x1cn/secure-k8s-aiops/issues/3) Klaster kind z Cilium i Hubble | Lokalny klaster, w którym CNI egzekwuje NetworkPolicy i raportuje odrzucone połączenia. | R1 Platforma | T02 | MVP | tak | zamknięte |
| [T04](https://github.com/l3x1cn/secure-k8s-aiops/issues/4) Powtarzalne wdrożenie: Makefile, Kustomize, namespace'y | Cała platforma stawiana i usuwana jedną komendą, za każdym razem z tym samym wynikiem. | R1 Platforma | T03 | MVP | tak | zamknięte |
| [T05](https://github.com/l3x1cn/secure-k8s-aiops/issues/5) Usługi frontend i orders z metrykami i logami JSON | Dwie usługi demonstracyjne, które generują realistyczne metryki i logi. | R3 Obserwowalność | T02 | MVP |  | zamknięte |
| [T06](https://github.com/l3x1cn/secure-k8s-aiops/issues/6) CI: lint, testy jednostkowe, gitleaks, walidacja manifestów | Każdy PR jest automatycznie sprawdzany, a łańcuch dostaw CI jest zabezpieczony. | R2 Bezpieczeństwo | T02 | MVP |  | zamknięte |
| [T07](https://github.com/l3x1cn/secure-k8s-aiops/issues/7) Model zagrożeń i macierz kontroli | Zespół wie, przed czym się broni, a każdy wymóg bezpieczeństwa ma kontrolę i test. | R2 Bezpieczeństwo | — | MVP |  | zamknięte |
| [T08](https://github.com/l3x1cn/secure-k8s-aiops/issues/8) Wstrzykiwanie awarii w orders i obraz fault-runner | Kontrolowane, powtarzalne awarie potrzebne do uczenia i oceny detekcji. | R4 AI/ML | T05 | MVP |  | zamknięte |
| [T09](https://github.com/l3x1cn/secure-k8s-aiops/issues/9) Prototyp detektora na danych syntetycznych | Wybrać metodę detekcji i regułę progu, zanim powstaną prawdziwe dane. | R4 AI/ML | — | MVP |  | zamknięte |

## Sprint 2 — Bezpieczeństwo i obserwowalność

| Zadanie | Cel | Rola | Zależy od | Zakres | KO | Stan |
|---|---|---|---|---|---|---|
| [T10](https://github.com/l3x1cn/secure-k8s-aiops/issues/10) Budowa obrazów w CI i publikacja do GHCR | Obrazy budowane powtarzalnie i dostępne dla wdrożenia chmurowego. | R1 Platforma | T05, T06 | MVP |  | zamknięte |
| [T11](https://github.com/l3x1cn/secure-k8s-aiops/issues/11) RBAC: konta usług i role zespołu | Ograniczyć uprawnienia — żaden pod nie rozmawia z API klastra, a ludzie widzą tylko to, czego potrzebują. | R2 Bezpieczeństwo | T04 | MVP | tak | zamknięte |
| [T12](https://github.com/l3x1cn/secure-k8s-aiops/issues/12) NetworkPolicy: default-deny, dozwolone przepływy, test niedozwolonego połączenia | Połączenia spoza dozwolonych ścieżek są odrzucane, co udowadnia test i widać w Hubble. | R2 Bezpieczeństwo | T03, T04, T05 | MVP | tak | zamknięte |
| [T13](https://github.com/l3x1cn/secure-k8s-aiops/issues/13) Pod Security Admission i securityContext | Kontenery bez zbędnych uprawnień; klaster odrzuca pody uprzywilejowane. | R2 Bezpieczeństwo | T04, T05 | MVP | tak | zamknięte |
| [T14](https://github.com/l3x1cn/secure-k8s-aiops/issues/14) Sekrety generowane przy wdrożeniu i gitleaks pre-commit | Brak publicznych sekretów — żaden sekret nie trafia do repozytorium. | R2 Bezpieczeństwo | T04 | MVP | tak | zamknięte |
| [T15](https://github.com/l3x1cn/secure-k8s-aiops/issues/15) Skan obrazów i konfiguracji Trivy w CI | Obraz z krytyczną podatnością albo źle skonfigurowany manifest nie przechodzi CI. | R1 Platforma (przegląd: R2) | T10 | MVP | tak | zamknięte |
| [T16](https://github.com/l3x1cn/secure-k8s-aiops/issues/16) Metryki: kube-prometheus-stack, ServiceMonitory, reguły nagrywające | Metryki kontenerów, aplikacji i sieci w jednym Prometheusie, z nazwami wspólnymi dla alertów i ML. | R3 Obserwowalność | T03, T05 | MVP | tak | zamknięte |
| [T17](https://github.com/l3x1cn/secure-k8s-aiops/issues/17) Logi i zdarzenia: Loki + Grafana Alloy | Logi kontenerów i zdarzenia Kubernetes w Grafanie, gotowe do analizy. | R1 Platforma | T16 | MVP | tak | zamknięte |
| [T18](https://github.com/l3x1cn/secure-k8s-aiops/issues/18) Generator ruchu Locust | Stały, realistyczny ruch, na którym uczy się detektor. | R3 Obserwowalność | T05 | MVP |  | zamknięte |
| [T19](https://github.com/l3x1cn/secure-k8s-aiops/issues/19) Alerty regułowe, alert bezpieczeństwa i Mailpit | Alert dociera do zespołu, także przy próbie niedozwolonego połączenia. | R3 Obserwowalność | T16, T12 | MVP | tak | zamknięte |
| [T20](https://github.com/l3x1cn/secure-k8s-aiops/issues/20) Eksport danych i cechy z Prometheusa | Zbiór danych bazowych do uczenia i analizy. | R4 AI/ML | T16, T18 | MVP |  | zamknięte |
| [T21](https://github.com/l3x1cn/secure-k8s-aiops/issues/21) Orkiestrator scenariuszy awarii z etykietami | Powtarzalne przebiegi awarii ze znanymi oknami czasu (etykiety prawdy) do oceny detekcji. | R4 AI/ML | T08, T12 | MVP |  | w toku (PR #75) |

## Sprint 3 — Detekcja AI i alerty

| Zadanie | Cel | Rola | Zależy od | Zakres | KO | Stan |
|---|---|---|---|---|---|---|
| [T22](https://github.com/l3x1cn/secure-k8s-aiops/issues/22) Dashboardy Grafana: Platforma, Bezpieczeństwo, AIOps | Jeden rzut oka pokazuje stan platformy, bezpieczeństwa i detekcji. | R3 Obserwowalność | T16, T17, T19, T24 | MVP | tak | do zrobienia |
| [T23](https://github.com/l3x1cn/secure-k8s-aiops/issues/23) Model IsolationForest i trening na rozgrzewce | Model, który odróżnia ruch normalny od anomalii w danych z klastra. | R4 AI/ML | T09, T20 | MVP |  | do zrobienia |
| [T24](https://github.com/l3x1cn/secure-k8s-aiops/issues/24) Serwis anomaly-detector i alert AnomalyDetected | Detekcja anomalii działa w klastrze i kończy się alertem. | R4 AI/ML | T23, T17, T19 | MVP | tak | do zrobienia |
| [T25](https://github.com/l3x1cn/secure-k8s-aiops/issues/25) Detekcja hybrydowa: alert IncidentConfirmed | Decyzja hybrydowa — reguły i ML razem dają pewniejszy alert krytyczny. | R4 AI/ML (z R3) | T24, T19 | MVP |  | do zrobienia |
| [T26](https://github.com/l3x1cn/secure-k8s-aiops/issues/26) Pakiet testów bezpieczeństwa i test mutacyjny polityk | Jedna komenda dowodzi wszystkich wymogów bezpieczeństwa, a testy naprawdę wykrywają regresję. | R2 Bezpieczeństwo | T11, T12, T13, T14 | MVP | tak | zamknięte |
| [T27](https://github.com/l3x1cn/secure-k8s-aiops/issues/27) Testy obserwowalności i e2e przepływu alertu | Automatyczny dowód, że metryki, logi, dashboardy i alerty działają end-to-end. | R3 Obserwowalność (z R4) | T19, T22, T24 | MVP | tak | do zrobienia |
| [T28](https://github.com/l3x1cn/secure-k8s-aiops/issues/28) E2E w CI na kind | Powtarzalność potwierdzona na czystej maszynie przy każdej zmianie main. | R1 Platforma | T21, T26, T27 | MVP | tak | do zrobienia |
| [T29](https://github.com/l3x1cn/secure-k8s-aiops/issues/29) Przenośność: overlay cloud | Te same manifesty gotowe do zarządzanego Kubernetes — infrastrukturalna część hybrydowości. | R1 Platforma | T04, T10 | MVP |  | do zrobienia |

## Sprint 4 — Raport, demo, rozszerzenia

| Zadanie | Cel | Rola | Zależy od | Zakres | KO | Stan |
|---|---|---|---|---|---|---|
| [T30](https://github.com/l3x1cn/secure-k8s-aiops/issues/30) Ewaluacja detekcji: reguły vs ML vs hybryda | Liczby, które pokazują jakość detekcji i wartość ML względem reguł. | R4 AI/ML | T21, T24, T25 | MVP |  | do zrobienia |
| [T31](https://github.com/l3x1cn/secure-k8s-aiops/issues/31) Raport testów i mapa kryteriów odbioru | Jeden dokument, który dowodzi spełnienia kryteriów odbioru. | R2 Bezpieczeństwo (wszyscy dostarczają dowody) | T15, T26, T27, T28, T30 | MVP | tak | do zrobienia |
| [T32](https://github.com/l3x1cn/secure-k8s-aiops/issues/32) Dokumentacja, runbook i scenariusz demo | Każdy, także prowadzący, uruchomi i zaprezentuje platformę z samej dokumentacji. | R3 Obserwowalność | T28 | MVP |  | do zrobienia |
| [T33](https://github.com/l3x1cn/secure-k8s-aiops/issues/33) IaC: OpenTofu lokalnie i wdrożenie w chmurze | Infrastruktura jako kod i rzeczywiste wdrożenie hybrydowe. | R1 Platforma | T04, T29 | rozszerzenie |  | do zrobienia |
| [T34](https://github.com/l3x1cn/secure-k8s-aiops/issues/34) Automatyzacja reakcji: responder | Platforma sama ogranicza szkody po alercie. | R2 Bezpieczeństwo (z R4) | T19, T24 | rozszerzenie |  | do zrobienia |
| [T35](https://github.com/l3x1cn/secure-k8s-aiops/issues/35) Dashboard jakości detekcji | Jakość detekcji widoczna w Grafanie obok działania detektora. | R4 AI/ML (z R3) | T30 | rozszerzenie |  | do zrobienia |
| [T36](https://github.com/l3x1cn/secure-k8s-aiops/issues/36) Raport porównawczy wariantów architektury | Uzasadnić wybory architektury liczbami. | R3 Obserwowalność (z R1) | T26, T30 | rozszerzenie |  | do zrobienia |
