# Detekcja anomalii

Decyzja z prototypu na danych syntetycznych (T09, [`aiops/notebooks/01-prototyp.ipynb`](../aiops/notebooks/01-prototyp.ipynb)). Potwierdzą ją albo zmienią dane z klastra w T23 i T30.

## Decyzja

- **Metoda: IsolationForest**, zgodnie z kartą projektu. Potok jak w T23: `StandardScaler` + `IsolationForest(n_estimators=200, random_state=42)`, osobny model dla każdej usługi, uczony na 30 min rozgrzewki. Wynik = −`score_samples` (większy = bardziej anomalny).
- **Reguła progu: 95. percentyl wyników z okna rozgrzewki** (zamiast 99,5). Pojedyncze przekroczenia odfiltrowuje `for: 1m` alertu `AnomalyDetected`.
- **Spodziewany wynik:** IsolationForest prawdopodobnie nie spełni kryterium T23 (co najmniej 5 z 7 scenariuszy przy najwyżej 2 fałszywych alarmach na godzinę). W prototypie wykrywa średnio 3,6 z 7. S5 i S7 wykrywają za to reguły `PodRestarts` i `PolicyDeniedConnections`, więc liczą się w detektorze hybrydowym (T25, T30).

## Jak to sprawdziliśmy

- 20 przebiegów, w każdym 30 min rozgrzewki i S1–S7 w losowej kolejności, z przerwą 10 min przed każdym scenariuszem i po ostatnim (`--gap` z T21). Razem ok. 33 h ruchu po rozgrzewce.
- 9 cech z tabeli reguł nagrywających dla `frontend` i `orders`, krok 30 s:
  - ruch jak w T18: 10 ± 8 użytkowników, sinusoida o okresie 30 min;
  - poziomy bazowe z pomiarów T05/T08;
  - skutki scenariuszy na podstawie smoke testów T08.
- Definicje jak w T30: wykrycie = początek alertu usługi docelowej w [start, end + 5 min]; fałszywy alarm = początek alertu poza wszystkimi oknami [start − 1 min, end + 5 min]; alert = flaga utrzymana przez `for` reguły.
- Dwa warianty ruchu bazowego:
  - **bazowy**;
  - **trudniejszy**: dwa razy większy szum i jednorazowe piki w 2% kroków (+0,1 CPU, +150 ms p95, 3% błędów).
- Notebook jest deterministyczny: `uv run jupyter nbconvert --to notebook --execute aiops/notebooks/01-prototyp.ipynb`.

## Wyniki

| Detektor | Próg | Wykryte z 7 (bazowy) | Fałszywe alarmy / h (bazowy) | Wykryte z 7 (trudniejszy) | Fałszywe alarmy / h (trudniejszy) | F1 (bazowy) |
|---|---|---|---|---|---|---|
| IsolationForest | p99,5 (dotychczas w T23) | 1,60 | 0,03 | 0,40 | 0,00 | 0,37 |
| IsolationForest | **p95 (wybrany)** | 3,60 | 0,33 | 2,35 | 0,09 | 0,66 |
| IsolationForest | p90 | 4,55 | 1,06 | 4,40 | 0,76 | 0,74 |
| kroczący z-score | p95 | 7,00 | 0,00 | 6,90 | 0,00 | 1,00 |
| stałe progi (alerty regułowe) | — | 5,00 | 0,00 | 5,00 | 0,00 | 0,83 |

Mediana opóźnienia wykrycia dla detektorów ML to 1 min (`for: 1m`), a dla reguł 2 min.

Wykrycia według scenariusza, ruch bazowy (odsetek z 20 przebiegów):

| Scenariusz | IsolationForest p99,5 | IsolationForest p95 | z-score p95 | Stałe progi |
|---|---|---|---|---|
| S1 cpu | 0,20 | 0,65 | 1,00 | 0,00 |
| S2 memory | 0,05 | 0,15 | 1,00 | 1,00 |
| S3 errors | 0,30 | 0,90 | 1,00 | 1,00 |
| S4 latency | 0,10 | 0,25 | 1,00 | 1,00 |
| S5 crash | 0,10 | 0,60 | 1,00 | 1,00 |
| S6 spike | 0,85 | 1,00 | 1,00 | 0,00 |
| S7 scan | 0,00 | 0,05 | 1,00 | 1,00 |

Fałszywe alarmy na godzinę na 4 h czystego ruchu bez dryfu i z pamięcią `orders` rosnącą o 0,02 limitu na godzinę:

| Detektor | Bez dryfu | Z dryfem |
|---|---|---|
| IsolationForest p95 | 0,82 | 2,22 |
| IsolationForest p99,5 | 0,07 | 0,43 |
| z-score p95 | 0,01 | 0,01 |

## Dlaczego IsolationForest wypada słabo

IsolationForest dzieli przestrzeń tylko w zakresie wartości z treningu. Z tego wynikają dwa ograniczenia (komórka „Dlaczego IsolationForest gubi część scenariuszy” w notebooku):

1. **Cecha stała w rozgrzewce jest niewidoczna.** `restarts_increase5m` i `policy_drops_rate1m` są w ruchu normalnym równe 0, więc model nie robi na nich podziałów. Punkt z `policy_drops=6` i `restarts=3` ma ten sam wynik co punkt normalny (0,526 i 0,526). Stąd prawie zerowe wykrycia S7 i słabe S5.
2. **Nasycenie poza zakresem.** Wartość daleko poza zakresem treningu ma ten sam wynik co wartość tuż nad maksimum: pamięć 0,90 i pamięć 0,18 dostają 0,571. Próg p99,5 z ok. 60 punktów rozgrzewki to praktycznie wynik najbardziej skrajnego punktu (0,559). Anomalia w 1 z 9 cech (S1, S2, S4) ledwo go przekracza i często nie utrzymuje się przez `for: 1m`.

## Dlaczego próg p95

- p99,5 z rozgrzewki to praktycznie maksimum, a przez nasycenie wynik anomalii jest tylko trochę wyższy. Na p95 IsolationForest wykrywa ponad dwa razy więcej scenariuszy (3,6 zamiast 1,6 z 7) przy 0,33 fałszywego alarmu na godzinę.
- p90 wykrywa jeszcze więcej (4,55 z 7), ale już przy 1,06 fałszywego alarmu na godzinę bez dryfu. Przy powolnym dryfie fałszywe alarmy rosną: na p95 z 0,82 do 2,22 na godzinę (p90 z dryfem nie mierzyliśmy).
- Model uczony raz nie nadąża za dryfem, więc T24 powinien okresowo uczyć go od nowa na ostatnich 30 min bez aktywnych alertów. W prototypie tego nie sprawdzaliśmy.

## Alternatywa: kroczący z-score

Dla każdej cechy z = (x − średnia) / odchylenie z poprzednich 30 min, a wynik = max |z| po cechach. Odchylenie ma dolną granicę na cechę (`STD_FLOOR` w notebooku), bo `restarts` i `policy_drops` są stale zerowe.

- Wynik: 7 z 7 scenariuszy, praktycznie bez fałszywych alarmów, także na trudniejszym ruchu i przy dryfie (próg p95).
- Nie wybraliśmy go, bo karta projektu przewiduje IsolationForest.
- Jeśli T23 na danych z klastra nie osiągnie kryterium, z-score jest pierwszym kandydatem do „próby poprawy”.
- To samo |z| na cechę jest potrzebne w T24 do logu z 3 najważniejszymi cechami, więc kod się przyda w obu przypadkach.

## Ryzyka dla innych zadań

- **S1 i HighCPU (T19, T21).** W prototypie S1 trwał 2 min i reguły nie wykryły go ani razu: `HighCPU` ma `for: 2m`, więc warunek musi być spełniony w 5 kolejnych ewaluacjach co 30 s (120–150 s zależnie od fazy ewaluacji). T21 wydłużył S1 do 4 min na podstawie modelu, w którym przy pełnym obciążeniu `service:cpu_usage_ratio_of_limit` (rate z 1 min) przekracza 0,8 od ok. 48 s po starcie awarii do ok. 12 s po jej końcu, czyli przez czas awarii minus 36 s (204 s przy 4 min). Pomiar w przebiegu `t21-pelny` (2026-11-24) temu przeczy: `service:cpu_usage_ratio_of_limit{service="orders"}` co 30 s od startu S1 wynosił 0,04; 0,01; 0,40; 1,00; 0,71; 0,75; 1,00; 1,00; 1,00; 1,00; 0,45; 0,01; 0,02. Spadek do 0,71 i 0,75 po 120 i 150 s wyzerował licznik `for`, więc `HighCPU` był tylko w stanie pending (najwyżej ok. 105 s), nie wystrzelił i nie wysłał e-maila: 4 min nie zawsze wystarczają. Dłuższy S1, krótszy `for` w `HighCPU` albo przyjęcie, że reguły nie wykrywają S1, to osobna decyzja; T21 nie zmienia reguły `HighCPU`.
- **Dane są syntetyczne.** Skutki scenariuszy i szum wynikają z założeń prototypu. Rozkłady, korelacje i sezonowość ruchu bazowego z klastra pokazuje [`aiops/notebooks/02-eda.ipynb`](../aiops/notebooks/02-eda.ipynb) (T20); różnice co najmniej 2× względem założeń prototypu (prototyp → klaster): CPU/limit, wyraz wolny (frontend): 0,04 → 0,0028; CPU/limit na 1 żądanie/s (frontend): 0,009 → 0,0028; B wysłane na żądanie, mediana (frontend): 1600 → 759; p95 (s), wyraz wolny (frontend): 0,03 → 0,0048; p95 (s) na 1 żądanie/s (frontend): 0,0008 → −1,1e-06; udział 5xx, średnia (frontend): 0,001 → 0; CPU/limit, wyraz wolny (orders): 0,03 → 0,0026; CPU/limit na 1 żądanie/s (orders): 0,01 → 0,0026; p95 (s), wyraz wolny (orders): 0,012 → 0,0048; p95 (s) na 1 żądanie/s (orders): 0,0004 → 3,0e-07; udział 5xx, średnia (orders): 0,001 → 0. Liczby detekcji z klastra da T30.
