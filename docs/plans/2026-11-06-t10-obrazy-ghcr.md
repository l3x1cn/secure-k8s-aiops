# T10 · Budowa obrazów w CI i publikacja do GHCR (issue #10)

## Context

Issue #10 (T10, R1, Sprint 2, zależy od T05 i T06; oba scalone): obrazy mają się budować powtarzalnie i być dostępne dla wdrożenia chmurowego. Zakres z issue:
- `.github/workflows/images.yml`:
  - matrix obrazów: frontend, orders, fault-runner (anomaly-detector dochodzi w T24);
  - Docker Buildx, tagi `sha-<7 znaków>`, etykieta OCI `org.opencontainers.image.source`.
- Push do `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>` tylko z `main`. `packages: write` tylko w jobie push. Pakiety publiczne.
- Lokalnie bez zmian: `make images` buduje `:dev` i ładuje obrazy do kind.

Kryteria akceptacji: (1) push na `main` publikuje obrazy widoczne w GHCR; (2) PR buduje obrazy bez publikacji.

Stan docelowy:
- W każdym PR workflow Images buduje trzy obrazy tokenem tylko do odczytu. Zbiorczy job `images` jest wymaganą kontrolą rulesetu `main`.
- Każdy push na `main` publikuje `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:sha-<7 znaków SHA commita>` w publicznych pakietach GHCR.
- `make images` działa jak dotąd.
- Kontrakt obrazów jest opisany w `docs/architektura.md`.

Decyzja właściciela (2026-11-06): budowa obrazów w PR blokuje scalenie przez jeden zbiorczy job `images` (`needs: build`) dopisany do wymaganych kontroli rulesetu `main (T06)`. T15 (Trivy) i T24 (nowy obraz) nie zmieniają już rulesetu.

Ustalone fakty (sprawdzone 2026-11-06):
- Repozytorium i GitHub:
  - `main` = `6192151` (PR #48), drzewo czyste, brak otwartych PR;
  - PR-y są scalane squashem, więc commit na `main` różni się od head PR (#48: `6192151`, head `02bf564`);
  - w `.github/workflows/` jest tylko `ci.yml` (T06). `.github/dependabot.yml` (ekosystem `github-actions`, `directory: "/"`) obejmie nowe akcje bez zmian;
  - Actions: `{"enabled":true,"allowed_actions":"all","sha_pinning_required":true}`, `default_workflow_permissions: read`;
  - ruleset `main (T06)`, id `26652123`: reguły `deletion`, `non_fast_forward`, `pull_request` (1 zatwierdzenie) i `required_status_checks` (`lint`, `unit`, `secrets`, `manifests`, `integration_id` 15368), `strict_required_status_checks_policy: false`, bez wyjątków;
  - współpracownicy: `l3x1cn` (admin), `DreadGoblin` (write);
  - `gh` jest zalogowany jako `l3x1cn` ze scope'ami `gist`, `read:org`, `repo` i `workflow`, bez `read:packages`. API pakietów (`/users/l3x1cn/packages`) zwraca więc 403 i GHCR sprawdzamy anonimowo przez rejestr;
  - anonimowy token `https://ghcr.io/token?scope=repository:l3x1cn/secure-k8s-aiops/<nazwa>:pull` dla frontend, orders i fault-runner → HTTP 403. Publicznego pakietu nie ma; prywatnego od nieistniejącego tą metodą nie odróżnimy. Ta sama metoda dla `astral-sh/uv:0.13.1` daje manifest z HTTP 200;
  - lokalnie Docker 29.9.2 z buildx 0.38.2, bez logowania do jakiegokolwiek rejestru (`~/.docker/config.json` bez `auths`).
- GHCR (dokumentacja GitHuba):
  - pierwsza publikacja pakietu konta osobistego tworzy pakiet prywatny. Pakiet połączony z repozytorium dziedziczy uprawnienia dostępu, ale nie widoczność;
  - publikacja `GITHUB_TOKEN`-em z workflow sama łączy pakiet z repozytorium. `GITHUB_TOKEN` nie wypchnie obrazu do pakietu, który już istnieje i nie jest połączony z repozytorium;
  - widoczność zmienia się tylko w UI (Package settings → Danger Zone → Change visibility), REST API tego nie obsługuje. Pakietu publicznego nie da się z powrotem zrobić prywatnym;
  - publiczne obrazy GHCR pobiera się anonimowo;
  - adres pakietu: `https://github.com/users/l3x1cn/packages/container/package/secure-k8s-aiops%2F<nazwa>` (format `html_url` z API pakietów). Adres ustawień `https://github.com/users/l3x1cn/packages/container/secure-k8s-aiops%2F<nazwa>/settings` jest wyprowadzony ze ścieżki formularza `…/settings/change_visibility` (unverified — confirm first; zapasowa droga: strona pakietu → „Package settings” po prawej).
- Piny akcji, sprawdzone przez `git ls-remote` i `gh api …/commits/<sha>` (tagi wskazują wprost commity):
  - `actions/checkout` v7.0.1 = `3d3c42e5aac5ba805825da76410c181273ba90b1` (jak w `ci.yml`);
  - `docker/setup-buildx-action` v4.4.1 = `f87e5991a6d7451dcb8d9637bfbc97413f497069` (2026-09-16);
  - `docker/login-action` v4.7.0 = `81c6f93d4bc991e510b342a00b419b3bb4efc5c6` (2026-10-23). Najnowsze v4.8.0 wyszło 2026-11-05, czyli przed końcem 7-dniowego cooldownu z `dependabot.yml`; Dependabot zaproponuje je sam;
  - `docker/metadata-action` v6.2.0 = `dc802804100637a589fabce1cb79ff13a1411302` (2026-07-02);
  - `docker/build-push-action` v7.4.0 = `c3c9e263c25d99ce0380d002d59b67737d91b0dc` (2026-09-15);
  - wszystkie cztery akcje Dockera działają na `node24`. Inputy `context`, `file`, `push`, `tags`, `labels`, `images`, `flavor`, `registry`, `username` i `password` są w `action.yml` pod tymi SHA.
- Zachowanie akcji:
  - metadata-action: `type=sha` daje `sha-` i 7 pierwszych znaków SHA commita zdarzenia. W `pull_request` to commit scalający `refs/pull/N/merge`, nie head PR;
  - metadata-action: `latest` powstaje tylko dla typów tag, semver, pep440 i match, a `flavor: latest=false` wyklucza go jawnie. Domyślne etykiety to m.in. `org.opencontainers.image.source`, `revision` (pełny SHA), `created`, `title` i `version`;
  - build-push-action: domyślny kontekst to kontekst Git, bez drzewa roboczego. `context: .` z checkoutem daje ten sam kontekst co `make images`, czyli korzeń repozytorium z `.dockerignore`;
  - build-push-action w publicznym repozytorium dodaje domyślnie atestację provenance `mode=max`. Obraz w GHCR jest wtedy indeksem: manifest linux/amd64 i manifest atestacji. Dockerfile'e nie mają `ARG`, więc atestacja nie ujawnia argumentów budowy;
  - build-push-action bez `push` i bez `load` zostawia wynik tylko w cache buildera.
- Szkic `images.yml` z Task 1 sprawdzono w katalogu tymczasowym:
  - `actionlint` 1.7.12: bez błędów;
  - `zizmor` 1.32.0 online: `No findings to report`;
  - persona `auditor`: tylko `concurrency-limits`, odrzucone już w przeglądzie T06, bo kosztuje wyłącznie minuty runnera;
  - na `main` `zizmor .github` też daje `No findings to report`.
- `actionlint` 1.7.12 i `zizmor` 1.32.0 są zainstalowane w mise globalnie, poza `mise.toml`. Uruchamia się je przez `mise exec <narzędzie>@<wersja> --`.
- `Makefile`:
  - `IMAGE_REPO := ghcr.io/l3x1cn/secure-k8s-aiops` w linii 13;
  - cel `images` (linie 91–97) buduje `:dev` z korzenia repozytorium z `--provenance=false` i ładuje obrazy do kind;
  - Dockerfile'e: `services/frontend/Dockerfile`, `services/orders/Dockerfile` i `chaos/Dockerfile` (obraz fault-runner).
- Manifesty w `deploy/base` podają obrazy bez tagu, a overlay `local` ustawia `dev`.
- `uv.lock` zmienił się w PR #47 i #48, a CI nie budował dotąd obrazów.
- Zadania zależne:
  - T15 dodaje w `images.yml` `trivy image` przed push i wymaga zablokowania testowego PR;
  - T24 dopisuje anomaly-detector do matrixa;
  - T29 (overlay `cloud`) używa tagów `sha-…`.
- Krok „Set up job” w logu joba GitHub Actions wypisuje grupę `GITHUB_TOKEN Permissions`, np. `Contents: read` i `Metadata: read` w jobie `lint` przebiegu `42280693296`.
- Przegląd T06 (`docs/reviews/2026-11-05-t06-ci.md`, otwarta uwaga DOC-001): drzewo w „Struktura repozytorium” nie ma katalogu `.github/`.

## Warunek wstępny (główny agent, przed startem delivery)

Katalog roboczy: korzeń repo na `main`, `git status --short` pusty. Po `git pull --ff-only` `main` zawiera `6192151`. Delivery startuje z `main` na gałęzi `t10-obrazy-ghcr` (konwencja `txx-krotki-opis` z README).

Wymagane:
- sieć i działający Docker;
- `gh auth status` → konto `l3x1cn` ze scope'ami `repo` i `workflow`. Scope `workflow` jest potrzebny do pushu plików z `.github/workflows/`;
- `mise ls actionlint zizmor` → `actionlint 1.7.12` i `zizmor 1.32.0`.

## Approach

Oba taski należą do stosu „pozostałe” (YAML, Makefile, Markdown). Kolejność 1 → 2, bo Task 2 opisuje joby i nazwy z Task 1. Ruleset, PR testowy i dowody kryteriów wymagają GitHuba, więc są w sekcjach „Po dostarczeniu” i „Po scaleniu”.

### Task 1: Workflow Images i powiązanie z celem images w Makefile
**Commit:** ci: workflow Images: budowa obrazów w PR i publikacja do GHCR z main

**Files:**
- Create: `.github/workflows/images.yml`
- Modify: `Makefile`

1. Utwórz `.github/workflows/images.yml` z treścią poniżej. Decyzje w tej treści:
   - Dwa joby z tym samym matrixem, bo `permissions` nie mogą zależeć od zdarzenia:
     - `build` działa w PR z `contents: read`;
     - `push` działa przy pushu na `main` i jako jedyny ma `packages: write`. Na `main` obrazy buduje tylko ten job.
   - `images` (`needs: build`, `!cancelled()`) daje jeden kontekst wymaganej kontroli, niezależny od liczby obrazów w matrixie.
   - Bez filtrów `paths`, jak w `ci.yml`: wymagana kontrola, która się nie uruchomi, blokowałaby PR na zawsze.
   - `fail-fast: false`: każdy obraz ma własny wynik.
   - `flavor: latest=false`: powstają tylko niezmienne tagi `sha-…`.
   - Bez `cache-from` i `cache-to`: każdy przebieg buduje od zera, ok. 1–2 min na obraz. PR nie może więc zatruć cache, z którego korzysta publikacja z `main`.
   - Bez `platforms` i QEMU: obraz ma jedną platformę, platformę runnera linux/amd64.
   - Bez `concurrency`, jak w `ci.yml`: każdy commit na `main` dostaje własne obrazy.
   - `provenance` zostaje domyślne. `--provenance=false` z `make images` dotyczy tylko `kind load`.
   - `packages: write` ma komentarz, którego wymaga audyt zizmor `undocumented-permissions`.

```yaml
# Obrazy (T10): Docker Buildx buduje obrazy projektu z korzenia repozytorium (workspace uv), jak `make images`.
# - PR: job build buduje każdy obraz bez publikacji (token tylko do odczytu). Job images to jedna wymagana
#   kontrola rulesetu main, zielona tylko wtedy, gdy zbudowały się wszystkie obrazy; zmiana nazwy joba images
#   wymaga zmiany rulesetu.
# - Push na main: job push, jedyny z packages: write, publikuje ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:sha-<7 znaków
#   SHA commita>; tagu latest nie ma.
# Tagi i etykiety OCI (m.in. org.opencontainers.image.source i revision) nadaje docker/metadata-action.
# context: . zamiast domyślnego kontekstu Git akcji build-push: budowa z drzewa roboczego i .dockerignore, jak lokalnie.
# Lista obrazów jest w matrixach jobów build i push oraz w celu images w Makefile: zmieniaj razem.
# Akcje przypięte po pełnym SHA commita z komentarzem wersji, jak w ci.yml; podbija je Dependabot.
name: Images

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

env:
  # = IMAGE_REPO z Makefile: zmieniaj razem.
  IMAGE_REPO: ghcr.io/l3x1cn/secure-k8s-aiops

jobs:
  build:
    name: build (${{ matrix.image }})
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    # Jak w ci.yml: zapas na zawieszenie, popraw po pomiarze czasu budowy w CI.
    timeout-minutes: 15
    strategy:
      # Każdy obraz ma własny wynik: błąd jednego nie anuluje budowy pozostałych.
      fail-fast: false
      matrix:
        include:
          - image: frontend
            dockerfile: services/frontend/Dockerfile
          - image: orders
            dockerfile: services/orders/Dockerfile
          - image: fault-runner
            dockerfile: chaos/Dockerfile
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - id: meta
        uses: docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302 # v6.2.0
        with:
          images: ${{ env.IMAGE_REPO }}/${{ matrix.image }}
          tags: type=sha
          flavor: latest=false
      - uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          context: .
          file: ${{ matrix.dockerfile }}
          push: false
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}

  # Wymagana kontrola rulesetu main: jeden kontekst niezależny od listy obrazów w matrixie.
  images:
    name: images
    needs: build
    if: ${{ !cancelled() && github.event_name == 'pull_request' }}
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - name: Wszystkie obrazy zbudowane
        env:
          BUILD_RESULT: ${{ needs.build.result }}
        run: |
          echo "Wynik joba build: $BUILD_RESULT"
          test "$BUILD_RESULT" = success

  push:
    name: push (${{ matrix.image }})
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    permissions:
      contents: read
      packages: write # publikacja obrazów w GHCR
    strategy:
      fail-fast: false
      matrix:
        include:
          - image: frontend
            dockerfile: services/frontend/Dockerfile
          - image: orders
            dockerfile: services/orders/Dockerfile
          - image: fault-runner
            dockerfile: chaos/Dockerfile
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069 # v4.4.1
      - uses: docker/login-action@81c6f93d4bc991e510b342a00b419b3bb4efc5c6 # v4.7.0
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@dc802804100637a589fabce1cb79ff13a1411302 # v6.2.0
        with:
          images: ${{ env.IMAGE_REPO }}/${{ matrix.image }}
          tags: type=sha
          flavor: latest=false
      - uses: docker/build-push-action@c3c9e263c25d99ce0380d002d59b67737d91b0dc # v7.4.0
        with:
          context: .
          file: ${{ matrix.dockerfile }}
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

2. `Makefile`: dwie nowe linie komentarza; receptur i pozostałych linii nie zmieniaj.
   - Pod linią 12 `# Obrazy budowane w projekcie (w deploy/base bez tagu; overlay local ustawia :dev).` wstaw linię:
     `# CI (.github/workflows/images.yml, T10) publikuje je w GHCR z tagiem sha-<7 znaków SHA commita>; IMAGE_REPO jest też w env tego workflow: zmieniaj razem.`
   - Pod linią `# --provenance=false: atestacja BuildKit w magazynie obrazów containerd psuje kind load (kubernetes-sigs/kind#3795).`, czyli bezpośrednio nad `images:`, wstaw linię:
     `# Ta sama lista obrazów jest w matrixach jobów build i push w .github/workflows/images.yml: zmieniaj razem.`

Akceptacja zadania (korzeń repo):
- `mise exec actionlint@1.7.12 -- actionlint` → kod 0, brak wyjścia;
- `grep -c 'uses: ' .github/workflows/images.yml` → `9`;
- `grep -cE 'uses: [a-z-]+/[a-z-]+@[0-9a-f]{40} # v[0-9.]+$' .github/workflows/images.yml` → `9`;
- `grep -c 'packages: write' .github/workflows/images.yml` → `1`;
- `GH_TOKEN=$(gh auth token) mise exec zizmor@1.32.0 -- zizmor .github` → kod 0 i `No findings to report`. Liczba „suppressed” nie ma znaczenia;
- `git diff --numstat main -- Makefile` → `2	0	Makefile`, a obie dodane linie zaczynają się od `#`.

### Task 2: Kontrakt obrazów w docs/architektura.md i README
**Commit:** docs: kontrakt obrazów GHCR (T10) w architekturze i README

**Files:**
- Modify: `docs/architektura.md`
- Modify: `README.md`

1. `docs/architektura.md`: między sekcją `## Komponenty i wersje` a `## Namespace'y i Pod Security` (ok. linii 29) wstaw poniższą sekcję. Sekcja `## Komponenty i wersje` kończy się akapitem „Obrazy dostawców w przypiętych wersjach …” (ok. linii 27). Przed nową sekcją i po niej zostaw po jednej pustej linii.

```markdown
## Obrazy

Obrazy budowane w projekcie nazywają się `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>` (`IMAGE_REPO` w `Makefile`) i powstają z korzenia repozytorium (workspace uv): `docker build -f <Dockerfile> .`. Manifesty w `deploy/base` podają obraz bez tagu, a tag ustawia overlay.

| Obraz | Dockerfile | Zadanie |
|---|---|---|
| frontend | `services/frontend/Dockerfile` | T05 |
| orders | `services/orders/Dockerfile` | T05, T08 |
| fault-runner | `chaos/Dockerfile` | T08 |

- Lokalnie `make images` buduje tag `:dev` i ładuje go do węzłów kind (overlay `local`).
- CI, workflow Images (`.github/workflows/images.yml`, T10):
  - PR: job `build` buduje każdy obraz bez publikacji tokenem tylko do odczytu. Zbiorczy job `images` jest wymaganą kontrolą rulesetu `main` i jest zielony tylko wtedy, gdy zbudowały się wszystkie obrazy;
  - push na `main`: job `push`, jedyny z `packages: write`, publikuje tag `sha-<7 znaków SHA commita>`. Tagu `latest` nie ma;
  - komplet obrazów commita istnieje, gdy wszystkie joby `push` jego przebiegu są zielone. Overlay `cloud` (T29) używa tagu takiego commita;
  - etykiety OCI nadaje `docker/metadata-action`, m.in. `org.opencontainers.image.source` (adres repozytorium) i `org.opencontainers.image.revision` (pełny SHA commita).
- Pakiety w GHCR są publiczne, więc obraz pobiera się bez logowania. Pierwsza publikacja nowego obrazu tworzy pakiet prywatny, a API GitHuba nie zmienia widoczności. Właściciel repozytorium przełącza więc pakiet ręcznie w UI (Package settings → Danger Zone → Change visibility → Public). Tej zmiany nie da się cofnąć.
- Nowy obraz (np. anomaly-detector w T24) dopisuje się w czterech miejscach: matrixy jobów `build` i `push` w `images.yml`, cel `images` w `Makefile` i tabela powyżej. Ruleset się nie zmienia.
```

2. `docs/architektura.md`, sekcja `## Struktura repozytorium`: w bloku drzewa wstaw poniższą linię jako pierwszy wpis, bezpośrednio pod linią `.`. Po `.github/` jest 15 spacji, więc `#` wypada w tej samej kolumnie co w pozostałych liniach. Ta linia zamyka uwagę DOC-001 z `docs/reviews/2026-11-05-t06-ci.md`; tamtego pliku nie zmieniaj.

```text
├── .github/               # workflows/ci.yml: kontrole PR (T06); workflows/images.yml: obrazy i GHCR (T10); dependabot.yml (T06)
```

3. `README.md`, sekcja `## Jak pracujemy`: pod linią ``- Przed PR: `make lint unit gitleaks manifests` (te same kontrole co CI).`` wstaw linię:

```markdown
- Obrazy: PR je buduje (wymagana kontrola `images`), a push na `main` publikuje `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:sha-<7 znaków SHA commita>` ([docs/architektura.md](docs/architektura.md#obrazy)).
```

Akceptacja zadania (korzeń repo):
- `grep -n '^## ' docs/architektura.md` → pierwsze trzy wiersze to `## Komponenty i wersje`, `## Obrazy`, `## Namespace'y i Pod Security`;
- `ls services/frontend/Dockerfile services/orders/Dockerfile chaos/Dockerfile` → trzy pliki z tabeli;
- `grep -c '^├── .github/' docs/architektura.md` → `1`;
- `grep -c 'docs/architektura.md#obrazy' README.md` → `1`;
- `make lint` → kod 0. Ruff sprawdza też bloki kodu python w plikach .md, a nowe bloki nie są pythonowe.

## Critical files & anchors

- `Makefile`, linie 12–13 (`IMAGE_REPO`) i 91–97 (cel `images`): miejsca dwóch nowych komentarzy; receptury zostają bez zmian.
- `.github/workflows/ci.yml`, linie 1–7 (nagłówek), 27 (`timeout-minutes`) i 29 (pin checkout): konwencje, które `images.yml` powtarza.
- `docs/architektura.md`: granica sekcji w liniach 27–29, gdzie wchodzi „Obrazy”, i drzewo „Struktura repozytorium” w liniach 158–181.
- `README.md`, linie 90–95: „Jak pracujemy”.
- Ruleset GitHuba `main (T06)`, id `26652123`: lista wymaganych kontroli. `images` dochodzi w kroku 3 sekcji „Po dostarczeniu”.

## Verification

Warunki wstępne: korzeń repo na gałęzi `t10-obrazy-ghcr` po Task 2, `git status --short` pusty, działający Docker i sieć. Wszystko w jednej sesji bash z `set -o pipefail` i `mkdir -p reports`. Czas: ok. 5–10 min, głównie budowa trzech obrazów.

1. Workflowy i piny:
   - `mise exec actionlint@1.7.12 -- actionlint` → kod 0, brak wyjścia (sprawdza `ci.yml` i `images.yml`);
   - `GH_TOKEN=$(gh auth token) mise exec zizmor@1.32.0 -- zizmor .github` → `No findings to report`;
   - `grep -cE 'uses: [a-z-]+/[a-z-]+@[0-9a-f]{40} # v[0-9.]+$' .github/workflows/images.yml` → `9`.
2. `make images` bez zmian:
   - `git diff --numstat main -- Makefile` → `2	0	Makefile`;
   - `git diff -U0 main -- Makefile | grep -E '^\+[^+]'` → dwie linie, obie zaczynają się od `+#`.
3. Te same Dockerfile'e i ten sam kontekst co w CI budują się lokalnie przez Buildx. To dowód przed pierwszym przebiegiem w CI.

```bash
for spec in frontend:services/frontend/Dockerfile orders:services/orders/Dockerfile fault-runner:chaos/Dockerfile; do
  n=${spec%%:*}; f=${spec#*:}
  docker buildx build --load --provenance=false -f "$f" -t "ghcr.io/l3x1cn/secure-k8s-aiops/$n:t10-check" . || echo "BŁĄD: $n"
done 2>&1 | tee reports/t10-lokalnie.txt
grep -c 'BŁĄD' reports/t10-lokalnie.txt
docker image rm ghcr.io/l3x1cn/secure-k8s-aiops/frontend:t10-check ghcr.io/l3x1cn/secure-k8s-aiops/orders:t10-check ghcr.io/l3x1cn/secure-k8s-aiops/fault-runner:t10-check
```

   Oczekiwane: `grep -c` → `0`, a `docker image rm` wypisuje trzy linie `Untagged: …:t10-check`.
4. Dokumentacja:
   - `grep -n '^## ' docs/architektura.md` → pierwsze trzy wiersze: `## Komponenty i wersje`, `## Obrazy`, `## Namespace'y i Pod Security`;
   - `make lint` → kod 0.
5. `git status --short` → pusty (`reports/` jest w `.gitignore`).

## Po dostarczeniu: GitHub (PR, ruleset, kryterium 2)

Wykonuje główny agent po Verification i po code review bez CRITICAL/HIGH.

Przygotowanie, w jednej sesji bash: `set -o pipefail`, `R=l3x1cn/secure-k8s-aiops`, `IMG=l3x1cn/secure-k8s-aiops`, `B=$(git branch --show-current)`, `mkdir -p reports`. Po każdym `gh pr create` odczekaj 30 s przed `gh pr checks --watch`. Gdy `gh pr checks` wypisze `no checks reported`, czekaj kolejne 30 s i powtórz, najwyżej 5 razy.

1. Gałąź i PR T10:

```bash
git push -u origin "$B"
gh pr create --repo "$R" --base main --head "$B" --title "T10 · Budowa obrazów w CI i publikacja do GHCR" \
  --body "Closes #10 — opis i dowód kryteriów akceptacji po przebiegach na GitHubie."
PR=$(gh pr view "$B" --repo "$R" --json number --jq .number)
sleep 30
gh pr checks "$PR" --repo "$R" --watch --interval 15
gh pr checks "$PR" --repo "$R" --json name,bucket --jq '.[] | "\(.name) \(.bucket)"' | sort | tee reports/t10-checks.txt
```

   Oczekiwane kontrole:
   - z wynikiem `pass`: `build (fault-runner)`, `build (frontend)`, `build (orders)`, `images`, `lint`, `manifests`, `secrets`, `unit`;
   - z wynikiem `skipping`: kontrola `push …`. Nazwa pominiętego joba macierzowego może zawierać nierozwinięte `${{ matrix.image }}`.
2. Przebieg PR nie publikuje (kryterium 2, część 1):

```bash
HEAD_SHA=$(gh pr view "$PR" --repo "$R" --json headRefOid --jq .headRefOid)
RUN=$(gh run list --repo "$R" --workflow images.yml --event pull_request --commit "$HEAD_SHA" --limit 1 --json databaseId --jq '.[0].databaseId')
{
  echo "Images, przebieg $RUN (pull_request, head $HEAD_SHA): https://github.com/$R/actions/runs/$RUN"
  gh run view "$RUN" --repo "$R" --json jobs --jq '.jobs[] | "\(.name) \(.conclusion)"' | sort
  for n in frontend orders fault-runner; do
    JOB=$(gh run view "$RUN" --repo "$R" --json jobs --jq ".jobs[] | select(.name == \"build ($n)\") | .databaseId")
    gh run view --repo "$R" --job "$JOB" --log > "reports/t10-log-build-$n.txt"
    echo "== build ($n): uprawnienia GITHUB_TOKEN i tag zbudowanego obrazu"
    grep -oE '(Contents|Metadata|Packages): (read|write)' "reports/t10-log-build-$n.txt" | sort -u
    grep -oE "secure-k8s-aiops/$n:sha-[0-9a-f]{7}" "reports/t10-log-build-$n.txt" | sort -u
  done
} | tee reports/t10-pr.txt
```

   Oczekiwane w `reports/t10-pr.txt`:
   - `build (fault-runner) success`, `build (frontend) success`, `build (orders) success`, `images success`, a joby `push …` mają `skipped`;
   - przy każdym `build`: tylko `Contents: read` i `Metadata: read`, bez `Packages: write`;
   - przy każdym `build` dokładnie jeden tag `secure-k8s-aiops/<nazwa>:sha-xxxxxxx`.
3. Ruleset `main (T06)`: `images` dochodzi do wymaganych kontroli (decyzja właściciela). Pozostałe reguły przechodzą bez zmian przez odczyt i zapis.

```bash
RS=26652123
gh api "repos/$R/rulesets/$RS" \
  | jq '{name, target, enforcement, bypass_actors, conditions,
         rules: [.rules[] | if .type == "required_status_checks"
           then .parameters.required_status_checks += [{"context": "images", "integration_id": 15368}]
           else . end]}' \
  | gh api --method PUT "repos/$R/rulesets/$RS" --input - > reports/t10-ruleset.json
gh api "repos/$R/rulesets/$RS" --jq '[.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context] | join(" ")' | tee reports/t10-wymagane.txt
gh api "repos/$R/rules/branches/main" --jq '[.[].type] | sort | join(" ")'
gh pr checks "$PR" --repo "$R" --required --json name,bucket --jq '.[] | "\(.name) \(.bucket)"' | sort
```

   Oczekiwane:
   - `lint unit secrets manifests images`;
   - `deletion non_fast_forward pull_request required_status_checks`;
   - wymagane kontrole PR T10: `images pass`, `lint pass`, `manifests pass`, `secrets pass`, `unit pass`.
4. Test blokady: PR z zepsutym Dockerfile.
   - Utwórz gałąź: `git switch -c t10-test-dockerfile "$B"`.
   - Narzędziem edit dopisz na końcu `chaos/Dockerfile`, pod `CMD ["fault-runner", "idle"]`, linię `RUN false`.
   - Wykonaj:

```bash
docker buildx build --load --provenance=false -f chaos/Dockerfile -t t10-test-dockerfile . >/dev/null 2>&1; echo "docker buildx build exit=$?"
git commit -am "test(ci): RUN false w Dockerfile fault-runner dla kontroli images (T10, nie scalać)"
git push -u origin t10-test-dockerfile
gh pr create --repo "$R" --base main --head t10-test-dockerfile --title "T10 test: zepsuty Dockerfile (nie scalać)" \
  --body "Test wymaganej kontroli images z T10: RUN false w chaos/Dockerfile ma zablokować PR. PR zostanie zamknięty bez scalania."
PT=$(gh pr view t10-test-dockerfile --repo "$R" --json number --jq .number)
sleep 30
gh pr checks "$PT" --repo "$R" --watch --interval 15 || true
RUN_T=$(gh run list --repo "$R" --workflow images.yml --branch t10-test-dockerfile --event pull_request --limit 1 --json databaseId --jq '.[0].databaseId')
{
  echo "PR testowy #$PT, przebieg Images $RUN_T: https://github.com/$R/actions/runs/$RUN_T"
  gh pr checks "$PT" --repo "$R" --json name,bucket --jq '.[] | "\(.name) \(.bucket)"' | sort
  echo "wymagane:"
  gh pr checks "$PT" --repo "$R" --required --json name,bucket --jq '.[] | "\(.name) \(.bucket)"' | sort
  gh run view "$RUN_T" --repo "$R" --log-failed | grep -oE 'did not complete successfully: exit code: 1|Wynik joba build: [a-z]+' | sort -u
} | tee reports/t10-test-dockerfile.txt
git switch "$B"
gh pr close "$PT" --repo "$R" --delete-branch --comment "Test zakończony: wymagana kontrola images zablokowała PR. Zamknięte bez scalania."
git branch --list 't10-test-*'
```

   Oczekiwane:
   - `docker buildx build exit=1` przed pushem;
   - kontrole: `build (fault-runner) fail`, `build (frontend) pass`, `build (orders) pass`, `images fail`, `lint pass`, `manifests pass`, `secrets pass`, `unit pass` i `push …` z `skipping`;
   - wymagane: `images fail`, `lint pass`, `manifests pass`, `secrets pass`, `unit pass`;
   - w logu `did not complete successfully: exit code: 1` i `Wynik joba build: failure`;
   - PR zamknięty, gałąź usunięta, a `git branch --list` nic nie wypisuje.
5. Opis PR T10 i prośba o review.
   - Zapisz `reports/t10-pr.md` z treścią poniżej. Wstaw `$RUN` z kroku 2 i `$PT` z kroku 4.
   - Uruchom `gh pr edit "$PR" --repo "$R" --body-file reports/t10-pr.md --add-reviewer DreadGoblin`.
   - `gh pr view "$PR" --repo "$R" --json state,reviewRequests` → `OPEN` i prośba o review od `DreadGoblin`.
   - Nie scalaj: PR wymaga zatwierdzenia drugiej osoby.

```markdown
Closes #10

- `.github/workflows/images.yml` (workflow Images, każdy PR i push na `main`, domyślnie `permissions: contents: read`):
  - `build (<obraz>)`, tylko PR: Docker Buildx buduje frontend, orders i fault-runner z korzenia repozytorium, bez publikacji;
  - `images`, tylko PR: zielony, gdy zbudowały się wszystkie obrazy; nowa wymagana kontrola rulesetu `main (T06)`;
  - `push (<obraz>)`, tylko push na `main`, jedyny job z `packages: write`: publikuje `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:sha-<7 znaków SHA commita>`, bez `latest`.
- Tagi i etykiety OCI (m.in. `org.opencontainers.image.source` i `org.opencontainers.image.revision`) z `docker/metadata-action`.
- Akcje przypięte po pełnym SHA: setup-buildx v4.4.1, login v4.7.0 (v4.8.0 nie przeszło jeszcze 7-dniowego cooldownu), metadata v6.2.0, build-push v7.4.0; checkout jak w `ci.yml`.
- `make images` bez zmian: w `Makefile` doszły tylko dwa komentarze, które wiążą listę obrazów i `IMAGE_REPO` z workflow.
- Kontrakt obrazów: `docs/architektura.md`, sekcja „Obrazy”, i wiersz `.github/` w strukturze repozytorium (DOC-001 z przeglądu T06); skrót w README.
- Ruleset `main (T06)`: wymagane kontrole `lint`, `unit`, `secrets`, `manifests` i `images`.

Kryteria akceptacji:
- [ ] Push na main publikuje obrazy widoczne w GHCR: sprawdzane po scaleniu (przebieg Images na `main`, pakiety publiczne, anonimowy `docker pull`); dowód w komentarzu w #10.
- [x] PR buduje obrazy bez publikacji: przebieg https://github.com/l3x1cn/secure-k8s-aiops/actions/runs/<RUN>: joby `build` z tokenem `Contents: read` i `Metadata: read`, job `push` pominięty. PR testowy #<PT> (`RUN false` w `chaos/Dockerfile`): `images` fail, zamknięty bez scalania.

Po scaleniu właściciel ustawia trzy pakiety jako publiczne (Package settings → Danger Zone → Change visibility → Public); API GitHuba tego nie robi.

@DreadGoblin: od tego PR wymaganą kontrolą jest też `images`. Proszę o review.
```

## Po scaleniu: publikacja w GHCR i kryterium 1

Start: właściciel informuje, że PR T10 jest scalony po zatwierdzeniu `DreadGoblin`. Wykonuje główny agent.

Przygotowanie, w jednej sesji bash w korzeniu repo:

```bash
set -o pipefail
R=l3x1cn/secure-k8s-aiops
IMG=l3x1cn/secure-k8s-aiops
mkdir -p reports
PR=$(gh pr list --repo "$R" --state merged --head t10-obrazy-ghcr --json number --jq '.[0].number')
MAIN_SHA=$(gh pr view "$PR" --repo "$R" --json mergeCommit --jq .mergeCommit.oid)
TAG="sha-${MAIN_SHA:0:7}"
docker logout ghcr.io
```

1. Przebieg Images na `main`. Gdy `RUN` jest pusty, czekaj 30 s i powtórz `gh run list`, najwyżej 5 razy.

```bash
RUN=$(gh run list --repo "$R" --workflow images.yml --event push --commit "$MAIN_SHA" --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN" --repo "$R" --exit-status --interval 15
{
  echo "Images, przebieg $RUN (push na main, commit $MAIN_SHA, tag $TAG): https://github.com/$R/actions/runs/$RUN"
  gh run view "$RUN" --repo "$R" --json jobs --jq '.jobs[] | "\(.name) \(.conclusion)"' | sort
  for n in frontend orders fault-runner; do
    JOB=$(gh run view "$RUN" --repo "$R" --json jobs --jq ".jobs[] | select(.name == \"push ($n)\") | .databaseId")
    gh run view --repo "$R" --job "$JOB" --log > "reports/t10-log-push-$n.txt"
    echo "== push ($n): uprawnienia GITHUB_TOKEN i opublikowany obraz"
    grep -oE '(Contents|Metadata|Packages): (read|write)' "reports/t10-log-push-$n.txt" | sort -u
    grep -oE "ghcr\.io/$IMG/$n:sha-[0-9a-f]{7}" "reports/t10-log-push-$n.txt" | sort -u
  done
} | tee reports/t10-main.txt
```

   Oczekiwane:
   - `push (fault-runner) success`, `push (frontend) success`, `push (orders) success`, a joby `build …` i `images` mają `skipped`;
   - przy każdym `push`: `Contents: read`, `Metadata: read`, `Packages: write`;
   - przy każdym `push` tag `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:$TAG`.
2. Widoczność pakietów: krok ręczny właściciela, bo API go nie obsługuje.
   - Agent przekazuje właścicielowi narzędziem `ask` trzy adresy ustawień i czeka na potwierdzenie:
     - `https://github.com/users/l3x1cn/packages/container/secure-k8s-aiops%2Ffrontend/settings`;
     - `https://github.com/users/l3x1cn/packages/container/secure-k8s-aiops%2Forders/settings`;
     - `https://github.com/users/l3x1cn/packages/container/secure-k8s-aiops%2Ffault-runner/settings`.
   - Gdy adres ustawień zwraca 404, właściciel otwiera stronę pakietu `https://github.com/users/l3x1cn/packages/container/package/secure-k8s-aiops%2F<nazwa>` i klika „Package settings” po prawej.
   - Na każdej stronie właściciel wybiera „Danger Zone” → „Change visibility” → „Public”, wpisuje nazwę pakietu (np. `secure-k8s-aiops/frontend`) i potwierdza.
   - Przy okazji sprawdza, że sekcja dostępu pokazuje repozytorium `secure-k8s-aiops`, czyli że pakiet jest połączony z repo.
3. Publikacja widoczna anonimowo (kryterium 1):

```bash
{
  echo "GHCR bez logowania:"
  for n in frontend orders fault-runner; do
    tok=$(curl -fsS "https://ghcr.io/token?scope=repository:$IMG/$n:pull" | jq -r .token)
    echo "== $n, tagi: $(curl -fsS -H "Authorization: Bearer $tok" "https://ghcr.io/v2/$IMG/$n/tags/list" | jq -c .tags)"
    docker pull -q "ghcr.io/$IMG/$n:$TAG"
    docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.source"}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "ghcr.io/$IMG/$n:$TAG"
  done
} | tee reports/t10-ghcr.txt
```

   Oczekiwane dla każdego obrazu:
   - lista tagów zawiera `"$TAG"`;
   - `docker pull` wypisuje `ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:$TAG`;
   - etykiety: `https://github.com/l3x1cn/secure-k8s-aiops $MAIN_SHA`.
4. Tagi z przebiegów PR nie istnieją w GHCR (kryterium 2, część 2):

```bash
for br in t10-obrazy-ghcr t10-test-dockerfile; do
  for run in $(gh run list --repo "$R" --workflow images.yml --event pull_request --branch "$br" --limit 50 --json databaseId --jq '.[].databaseId'); do
    gh run view "$run" --repo "$R" --log | grep -oE 'secure-k8s-aiops/(frontend|orders|fault-runner):sha-[0-9a-f]{7}'
  done
done | sort -u > reports/t10-tagi-pr.txt
wc -l < reports/t10-tagi-pr.txt
while read -r ref; do
  n=${ref#secure-k8s-aiops/}; n=${n%%:*}; t=${ref##*:}
  tok=$(curl -fsS "https://ghcr.io/token?scope=repository:$IMG/$n:pull" | jq -r .token)
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $tok" \
    -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/$IMG/$n/manifests/$t")
  echo "tag z PR $ref → HTTP $code"
done < reports/t10-tagi-pr.txt | tee -a reports/t10-ghcr.txt
```

   Oczekiwane: `wc -l` → co najmniej `3` (co najmniej jeden tag na obraz), a każda linia kończy się na `HTTP 404`.
5. Dowód w issue #10, opis PR i informacja dla zadań zależnych:

````bash
{
  echo "## Dowód kryteriów akceptacji T10"; echo
  echo "PR #$PR, commit na main \`$MAIN_SHA\`, tag \`$TAG\`."; echo
  echo "### 1. Push na main publikuje obrazy widoczne w GHCR"; echo
  echo '```text'; cat reports/t10-main.txt; echo; cat reports/t10-ghcr.txt; echo '```'; echo
  echo "Pakiety (publiczne): https://github.com/users/l3x1cn/packages/container/package/secure-k8s-aiops%2Ffrontend, https://github.com/users/l3x1cn/packages/container/package/secure-k8s-aiops%2Forders, https://github.com/users/l3x1cn/packages/container/package/secure-k8s-aiops%2Ffault-runner"; echo
  echo "### 2. PR buduje obrazy bez publikacji"; echo
  echo "Joby build mają token tylko do odczytu, job push jest w PR pominięty, a żaden tag z przebiegów PR nie istnieje w GHCR (HTTP 404 w sekcji 1)."; echo
  echo '```text'; cat reports/t10-pr.txt; echo; cat reports/t10-test-dockerfile.txt; echo '```'
} > reports/t10-dowod.md
URL=$(gh issue comment 10 --repo "$R" --body-file reports/t10-dowod.md)
echo "$URL"
````

   - W `reports/t10-pr.md` zmień pierwszy checkbox na `- [x] Push na main publikuje obrazy widoczne w GHCR: dowód <URL>` i wstaw `$URL`. Potem `gh pr edit "$PR" --repo "$R" --body-file reports/t10-pr.md`. Checkboxów w issue nie zaznaczaj; zaznaczone są w opisie PR, jak w T03, T04 i T06.
   - Komentarz w #24: `gh issue comment 24 --repo "$R" --body "<treść>"`, gdzie `<treść>` to:
     „T10: obraz anomaly-detector dopisz w czterech miejscach: matrixy jobów `build` i `push` w `.github/workflows/images.yml`, cel `images` w `Makefile` i tabela „Obrazy” w `docs/architektura.md`. Po pierwszej publikacji z `main` pakiet `secure-k8s-aiops/anomaly-detector` jest prywatny i właściciel ustawia go jako publiczny w UI (Package settings → Danger Zone → Change visibility). Ruleset `main` nie wymaga zmian: wymagana kontrola `images` obejmuje cały matrix `build`.”
   - Komentarz w #15: `gh issue comment 15 --repo "$R" --body "<treść>"`, gdzie `<treść>` to:
     „T10: w `.github/workflows/images.yml` job `build` (matrix, tylko PR, `contents: read`) buduje obrazy z `push: false` i bez `load`, więc obraz nie trafia do Dockera runnera. Zbiorczy job `images` (`needs: build`) jest wymaganą kontrolą rulesetu `main`: błąd dowolnego kroku joba `build` blokuje PR bez zmian w rulesecie. Job `push` (tylko push na `main`, `packages: write`) buduje i publikuje.”
6. Sprzątanie: `docker image rm "ghcr.io/$IMG/frontend:$TAG" "ghcr.io/$IMG/orders:$TAG" "ghcr.io/$IMG/fault-runner:$TAG"`, a `git status --short` → pusty.

## Assumptions & contingencies

Założenia (właściciel może je zmienić):
- Wymagana kontrola to zbiorczy job `images`, nie osobne kontrole per obraz (decyzja właściciela z 2026-11-06).
- W GHCR są tylko tagi `sha-<7 znaków>`, bez `latest`.
- Obraz ma jedną platformę, linux/amd64. Zarządzane klastry z T33 (AKS, GKE, EKS) domyślnie mają węzły amd64.
- `docker/login-action` jest przypięty na v4.7.0 zamiast v4.8.0 przez 7-dniowy cooldown.
- Atestacja provenance zostaje domyślna (`mode=max`), więc w GHCR obraz ma też wpis `unknown/unknown`.
- CI nie używa cache budowania.
- Upublicznienie pakietów jest nieodwracalne, a issue go wymaga.
- Starych wersji `sha-…` nikt nie sprząta (brak polityki retencji); to poza T10.
- Commit ma komplet obrazów tylko wtedy, gdy wszystkie joby `push` jego przebiegu są zielone. Joby matrixa publikują niezależnie od siebie.

Plan awaryjny:
- `push (…)` kończy się błędem `denied` albo `permission_denied: write_package`:
  - przyczyna: pakiet już istnieje i nie jest połączony z repozytorium;
  - właściciel w ustawieniach pakietu, w sekcji „Manage Actions access”, dodaje repozytorium `secure-k8s-aiops` z rolą `Write`;
  - potem `gh run rerun "$RUN" --repo "$R" --failed`.
- Część jobów `push (…)` na `main` pada z innego powodu: jeden raz `gh run rerun "$RUN" --repo "$R" --failed`. Ponowne uruchomienie ma ten sam commit, więc publikuje brakujące obrazy z tym samym tagiem. Ponowny błąd: zatrzymaj się i zgłoś log joba.
- Błąd pobierania w `build` albo `push`, np. HTTP 429 `toomanyrequests` z Docker Hub dla `python:3.13.16-slim` albo `docker/dockerfile:1`, albo błąd PyPI w `uv sync`:
  - jeden raz `gh run rerun <run> --repo "$R" --failed`;
  - ponowny błąd: zatrzymaj się i zgłoś log kroku.
- `build` pada w CI z innego powodu niż sieć, a krok 3 Verification przeszedł: zatrzymaj się i zgłoś log. Dockerfile'i w T10 nie zmieniaj.
- Krok 3 Verification (lokalna budowa) pada: zatrzymaj się i zgłoś `reports/t10-lokalnie.txt`. Dockerfile'e nie należą do zakresu T10.
- zizmor zgłasza uwagi w domyślnej personie:
  - `unpinned-uses`, `artipacked`, `excessive-permissions`, `ref-version-mismatch` i `template-injection` przeczą wymaganiom planu: popraw `images.yml`;
  - pozostałe uwagi wypisz w opisie PR w sekcji „Uwagi zizmor” bez zmian w plikach.
- `gh api --method PUT … rulesets/26652123` zwraca 422:
  - powtórz raz z treścią zawierającą tylko `rules`, czyli z tym samym filtrem `jq`, ale w postaci `{rules: [...]}`;
  - ponowne 422: zatrzymaj się i zgłoś treść błędu. Nie usuwaj reguł ani wymaganych kontroli.
- `gh pr checks --required` nie pokazuje `images`:
  - porównaj `context` w `gh api "repos/$R/rulesets/26652123"` z nazwami z `gh pr checks`;
  - popraw nazwę tym samym poleceniem PUT i powtórz krok.
- W PR testowym `images` przechodzi mimo `build (fault-runner) fail`: zatrzymaj się i zgłoś log joba `images` (linia `Wynik joba build: …`).
- Po zmianie widoczności anonimowy `docker pull` zwraca `denied`: ten pakiet jest nadal prywatny, więc właściciel powtarza dla niego krok 2.
- `docker pull` zwraca `manifest unknown`: tag nie został opublikowany. Sprawdź wynik tego obrazu w `reports/t10-main.txt`.
- Tag z przebiegu PR zwraca HTTP 200 (krok 4 po scaleniu): PR opublikował obraz, co przeczy założeniu, że `packages: write` jest tylko w `push`. Zatrzymaj się i zgłoś przebieg, z którego pochodzi tag.
- Między scaleniem a weryfikacją scalono inne PR-y i lista tagów ma więcej wpisów `sha-…`: to poprawne. Kryterium wymaga tylko obecności `$TAG` i braku tagów z PR.
