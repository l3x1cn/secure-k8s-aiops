# T04 · Powtarzalne wdrożenie: Makefile, Kustomize, namespace'y (issue #4)

## Context

Issue #4 (T04, R1, Sprint 1, zależy od T03): cała platforma stawiana i usuwana jedną komendą, za każdym razem z tym samym wynikiem. Zakres z issue: `platform/versions.env` jako jedno źródło wersji chartów i obrazów zewnętrznych czytane przez Makefile; cele `up` (klaster → sekrety → platforma → aplikacje; rośnie z kolejnymi zadaniami), `down`, `images` (`:dev` i `kind load`), `deploy`, `status`, `urls`, `prometheus`, `alertmanager`; `deploy/base` z namespace'ami z sekcji „Namespace'y i Pod Security” i aplikacjami; `deploy/overlays/local` z NodePort 30080 dla frontendu, obrazami `:dev`, `imagePullPolicy: IfNotPresent` i `FAULTS_ENABLED=true`. Kryteria akceptacji: (1) `make down && make up` od zera dwa razy z rzędu — wszystkie pody Ready, `curl -fsS localhost:8080/healthz` zwraca 200, czas `make up` zapisany w README; (2) ponowne `make up` na działającym klastrze niczego nie zmienia ani nie psuje; (3) ten sam wynik na co najmniej dwóch maszynach zespołu.

Stan docelowy: `make up` stawia kind z Cilium i Hubble, namespace'y z etykietą PSA `enforce`, sekrety `orders-api-token` i `fault-token`, obrazy `frontend`, `orders` i `fault-runner` z tagiem `:dev` oraz overlay `local`; `make down` usuwa klaster.

Decyzje właściciela (2026-11-05):
- T04 startuje dopiero po scaleniu #39 (T05) i #40 (T08) do `main` (sekcja „Warunek wstępny”).
- Namespace'y dostają tylko etykietę `pod-security.kubernetes.io/enforce` według tabeli w `docs/architektura.md`; `warn`, `audit`, komentarz uzasadniający i test PSA zostają w T13.
- `prometheus-operator-crds` (T03) zostaje bez pliku values: chart ma tylko `crds.annotations` i `crds.<crd>.enabled` (wszystkie domyślnie `true`). Regułę Helm w opisie #4 doprecyzowuje krok „Po dostarczeniu”.

Ustalone fakty (sprawdzone 2026-11-05):
- `main` = `327eea3` (T03). Makefile ma cele `doctor`, `cluster`, `hubble-ui`, `hubble-relay`. `platform/versions.env` ma wersje i digesty chartów `cilium` 1.20.3 i `prometheus-operator-crds` 32.0.1 (jedyny konsument: `include` w Makefile). Obraz węzła `kindest/node:v1.36.4@sha256:099e…` stoi trzy razy w `platform/kind/cluster.yaml` (MAINT-001 w `docs/reviews/2026-10-21-delivery-t03-kind-cilium-hubble.md`).
- #39 i #40 (gałąź `origin/t08-wstrzykiwanie-awarii`, commit `eeb02ef`) dodają `deploy/base/kustomization.yaml` (`resources: [fault-runner, frontend, orders]`) i podkatalogi z `namespace: shop` albo `namespace: loadgen`. Obrazy w base to `ghcr.io/l3x1cn/secure-k8s-aiops/{frontend,orders,fault-runner}` bez tagu. Service `frontend` jest typu ClusterIP z portem `name: http`, `port: 8080`, `targetPort: http`. W kontenerze `orders` jest zmienna `FAULTS_ENABLED: "false"`. Każdy Deployment ma jeden kontener i etykietę `app.kubernetes.io/part-of: secure-k8s-aiops`. Dockerfile'e buduje się z korzenia repo (`docker build -f services/<nazwa>/Dockerfile .`, `docker build -f chaos/Dockerfile .`); używają `RUN --mount=type=cache`, więc wymagają BuildKit (Docker Buildx).
- Bez sekretów pody nie wstaną: frontend i orders mają `secretKeyRef` `orders-api-token`/`token` bez `optional` (CreateContainerConfigError), a fault-runner montuje wolumen z Secretu `fault-token` bez `optional` (ContainerCreating). Dlatego T04 dostarcza `make secrets` (`scripts/secrets.sh`) dla tych dwóch sekretów; T14 (zależy od T04) dopisze `grafana-admin`, `make grafana-password`, pre-commit i testy.
- Maszyna R1: Docker 29.9.2 z magazynem obrazów containerd (`driver-type io.containerd.snapshotter.v1`). kind 0.33.0 importuje obrazy przez `ctr images import --all-platforms` (`pkg/cluster/nodeutils/util.go`). Dla obrazów z atestacją BuildKit kończy się to błędem `ctr: mismatched image rootfs and manifest layers` (kubernetes-sigs/kind#3795, komentarz z 2026-11-02, Docker 29). Dlatego `make images` buduje z `--provenance=false`. Prawdopodobnie (wniosek z kind#3795 i kodu kind, niesprawdzony na żywo) przy tym magazynie ID obrazu w Dockerze to digest manifestu, a kind porównuje go z ID konfiguracji z `crictl`, więc `kind load` przy każdym uruchomieniu wypisze `not yet present … loading` i zaimportuje obraz ponownie. Ponowny import tego samego obrazu nie zmienia podów; sprawdza to krok 5 Verification.
- kind 0.33.0: `--image` nadpisuje obraz wszystkich węzłów z configu (`pkg/cluster/internal/create/create.go`, `fixupOptions`). `kind delete cluster` bez węzłów kończy się sukcesem (`pkg/cluster/internal/delete/delete.go`).
- kubectl 1.37.1 (sprawdzone na klastrze T03):
  - `rollout status deployment -l <selektor>` bez dopasowań wypisuje `No resources found in <ns> namespace.` i kończy się kodem 0;
  - `-o go-template` ma funkcje `base64decode` i `len`;
  - `get secret … --ignore-not-found` nic nie wypisuje i kończy się kodem 0 dla brakującego Secretu, brakującego klucza (przez `{{if}}`) i brakującego namespace'u;
  - `kubectl apply -f -` z pustym wejściem kończy się `error: no objects passed to apply` (kod 1), a nieudany `kustomize build` nic nie wypisuje na stdout.
- Prototyp overlayu z Task 2 na drzewie `deploy/` z `origin/t08-wstrzykiwanie-awarii`:
  - `kustomize build` (5.8.3) daje 10 obiektów: 5 Namespace (pierwsze w wyniku), 2 Service, 3 Deployment;
  - `kubeconform -strict` zwraca Valid 10/10;
  - Service `frontend` ma `type: NodePort`, `nodePort: 30080` i zachowany `targetPort: http`;
  - trzy obrazy `:dev` z `IfNotPresent`, a w `orders` jest `FAULTS_ENABLED: "true"`.

## Warunek wstępny (główny agent, przed startem delivery)

Katalog roboczy: korzeń repo, `git status --short` pusty.

```bash
git fetch origin --prune
gh pr view 39 --repo l3x1cn/secure-k8s-aiops --json state --jq .state
gh pr view 40 --repo l3x1cn/secure-k8s-aiops --json state --jq .state
git ls-tree -r --name-only origin/main -- deploy/base services/frontend/Dockerfile services/orders/Dockerfile chaos/Dockerfile
git grep -n 'name: FAULTS_ENABLED' origin/main -- deploy/base/orders/deployment.yaml
git grep -n 'image: ghcr.io/l3x1cn/secure-k8s-aiops/' origin/main -- deploy/base
```

Oczekiwane wyniki:
- oba PR mają stan `MERGED`;
- lista plików zawiera `deploy/base/kustomization.yaml`, `deploy/base/{frontend,orders}/{deployment,kustomization,service}.yaml`, `deploy/base/fault-runner/{deployment,kustomization}.yaml` i trzy Dockerfile'e;
- pierwszy `git grep` znajduje jedną linię;
- drugi `git grep` znajduje trzy linie obrazów bez tagu: `…/frontend`, `…/orders` i `…/fault-runner`.

Potem `git switch main && git pull --ff-only`. Delivery startuje z aktualnego `main`. Gdy któryś warunek nie jest spełniony, nie startuj delivery: zgłoś właścicielowi, który PR nie jest scalony albo którego pliku czy linii brakuje.

Środowisko wykonawcy (Task 2, 3, 5 i 6 oraz Verification używają klastra i Dockera):
- `docker info` działa bez sudo w powłoce agenta (`id -nG` zawiera `docker`);
- `docker buildx version` działa.

2026-11-05 na maszynie R1 obu brakowało: sesja omp była uruchomiona przed dodaniem użytkownika do grupy `docker`, a pakietu `docker-buildx` nie ma. Naprawia to właściciel (ponowne zalogowanie, `sudo pacman -S docker-buildx`); wykonawca nie zmienia konfiguracji systemu.

## Approach

Wszystkie zadania należą do stosu „pozostałe” (Makefile, YAML, bash, dokumentacja). Kolejność 1 → 6; po każdym zadaniu `make cluster` dalej działa. Zadania 1–3 nie zależą od siebie. Task 5 używa plików z Task 1–4, a Task 6 mierzy czas gotowego `make up`. Testów jednostkowych nie ma (CI to T06); dowód zachowania jest w Verification.

### Task 1: Obraz węzła kind w platform/versions.env
**Commit:** refactor(platform): obraz węzła kind w platform/versions.env

**Files:**
- Modify: `platform/versions.env`
- Modify: `platform/kind/cluster.yaml`
- Modify: `Makefile`

1. `platform/versions.env`: zastąp całą treść poniższą. Dochodzi klucz `KIND_NODE_IMAGE` i komentarz o Kubernetes 1.36 przeniesiony z `cluster.yaml`; pozostałe wartości bez zmian. Wartość zawiera `:` po `=`, więc `include` w Makefile czyta ją jako zmienną, tak jak istniejące `*_CHART_DIGEST`.

```make
# Wersje chartów Helm i obrazów zewnętrznych (T03, T04): jedno źródło dla Makefile i skryptów.
# Format KLUCZ=wartość, bez spacji i cudzysłowów. Wersja Cilium i obraz węzła kind są też w docs/architektura.md – zmieniaj razem.
# Charty OCI: *_VERSION i *_CHART_DIGEST zmieniaj razem; digest to linia „Digest:” z `helm pull <chart> --version <wersja>`.
# Obraz węzłów kind (make cluster, flaga --image): Kubernetes 1.36 zamiast domyślnego w kind 0.33.0 1.37, bo Cilium 1.20 jest testowany na 1.33–1.36.
KIND_NODE_IMAGE=kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed
CILIUM_VERSION=1.20.3
CILIUM_CHART_DIGEST=sha256:e84f73cc9edcb0d00306ecee57a56f20bb32dddad77c8cef3af62d844ec8adea
PROMETHEUS_OPERATOR_CRDS_VERSION=32.0.1
PROMETHEUS_OPERATOR_CRDS_CHART_DIGEST=sha256:6a5f0e0d7e53f0c9336d6ff56fbf4ff506a1a0d8251a26567b11cbbdef2c01b2
```

2. `platform/kind/cluster.yaml`: zastąp całą treść poniższą (bez pól `image:`, mapowania portów bez zmian):

```yaml
# Klaster kind (T03). Twórz przez `make cluster`: Makefile nadaje nazwę i obraz węzłów
# (KIND_NODE_IMAGE z platform/versions.env; flaga --image nadpisuje obraz wszystkich węzłów) i instaluje Cilium.
# Bez domyślnego CNI węzły są NotReady, dopóki Cilium nie wystartuje.
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
nodes:
  - role: control-plane
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
  - role: worker
```

3. `Makefile`, recepta `cluster`:
   - w linii `kind create cluster --name '$(CLUSTER_NAME)' --config platform/kind/cluster.yaml; \` wstaw ` --image '$(KIND_NODE_IMAGE)'` zaraz po `--name '$(CLUSTER_NAME)'`;
   - w komentarzu nad `cluster:` po linii `# a helm upgrade --install doprowadza CRD i Cilium do wersji i digestów z platform/versions.env.` dopisz linię `# Obraz węzłów: KIND_NODE_IMAGE z platform/versions.env (--image nadpisuje obraz wszystkich węzłów).`

   Bez `--image` i bez `image:` w configu kind wziąłby domyślny obraz z Kubernetes 1.37, więc obie zmiany idą w jednym commicie.

Akceptacja zadania:
- `make -n cluster | grep -c "kind create cluster --name 'secure-k8s-aiops' --image 'kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed' --config platform/kind/cluster.yaml"` → `1`;
- `grep -c 'image:' platform/kind/cluster.yaml` → `0`.

### Task 2: Namespace'y w deploy/base i overlay local
**Commit:** feat(deploy): namespace'y z Pod Security i overlay local dla kind

**Files:**
- Create: `deploy/base/namespaces.yaml`
- Modify: `deploy/base/kustomization.yaml`
- Create: `deploy/overlays/local/kustomization.yaml`
- Delete: `deploy/overlays/local/.gitkeep`

1. Utwórz `deploy/base/namespaces.yaml` z poniższą treścią. Wszystkie namespace'y z tabeli oprócz kube-system, który zostaje bez zmian. Plik jest w base, bo overlay `cloud` (T29) ma te same PSA. `make namespaces` (Task 5) stosuje go osobno przed sekretami.

```yaml
# Namespace'y z docs/architektura.md („Namespace'y i Pod Security”), T04; kube-system zostaje bez zmian.
# Etykieta enforce według tabeli; warn, audit i test Pod Security dodaje T13.
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    pod-security.kubernetes.io/enforce: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: loadgen
  labels:
    pod-security.kubernetes.io/enforce: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: aiops
  labels:
    pod-security.kubernetes.io/enforce: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: intruder
  labels:
    pod-security.kubernetes.io/enforce: restricted
---
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    # Wyjątek z tabeli: node-exporter (T16) i Alloy (T17) potrzebują dostępu do hosta.
    pod-security.kubernetes.io/enforce: privileged
```

2. `deploy/base/kustomization.yaml` (z #39/#40): dopisz `- namespaces.yaml` jako pierwszy element listy `resources`; pozostałych elementów nie zmieniaj. Oczekiwana treść przy stanie z #40:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespaces.yaml
  - fault-runner
  - frontend
  - orders
```

3. Utwórz `deploy/overlays/local/kustomization.yaml` z poniższą treścią (przetestowana w prototypie):
   - patch JSON6902 `imagePullPolicy` dotyczy wszystkich Deploymentów; każdy ma jeden kontener, a obrazy zewnętrzne przypięte po digeście mają tę samą politykę domyślnie;
   - patche strategic merge łączą listę portów po `port` i listę `env` po `name`.

```yaml
# Overlay local (kind, T04): obrazy :dev z `make images`, frontend na NodePort 30080 (localhost:8080), awarie włączone.
# Wdraża go `make deploy` (krok `make up`).
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
images:
  - name: ghcr.io/l3x1cn/secure-k8s-aiops/frontend
    newTag: dev
  - name: ghcr.io/l3x1cn/secure-k8s-aiops/orders
    newTag: dev
  - name: ghcr.io/l3x1cn/secure-k8s-aiops/fault-runner
    newTag: dev
patches:
  # Obrazy :dev są tylko w węzłach kind (`kind load`), nie w rejestrze.
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/imagePullPolicy
        value: IfNotPresent
  # localhost:8080 → NodePort 30080 (extraPortMappings w platform/kind/cluster.yaml).
  - patch: |-
      apiVersion: v1
      kind: Service
      metadata:
        name: frontend
        namespace: shop
      spec:
        type: NodePort
        ports:
          - name: http
            port: 8080
            nodePort: 30080
  # /faults/* dla fault-runnera (docs/architektura.md, „Scenariusze awarii”).
  - patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: orders
        namespace: shop
      spec:
        template:
          spec:
            containers:
              - name: orders
                env:
                  - name: FAULTS_ENABLED
                    value: "true"
```

4. Usuń `deploy/overlays/local/.gitkeep`, bo katalog ma już śledzony plik. `deploy/overlays/cloud/.gitkeep` zostaje (T29).

Akceptacja zadania:
- `mise exec -- kustomize build deploy/overlays/local | mise exec -- kubeconform -strict -summary -` → `Valid: 10, Invalid: 0, Errors: 0, Skipped: 0`;
- `mise exec -- kustomize build deploy/overlays/local | grep -E 'image: |imagePullPolicy|nodePort|type: NodePort'` → trzy linie `image: ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:dev`, trzy `imagePullPolicy: IfNotPresent`, `nodePort: 30080`, `type: NodePort`;
- `mise exec -- kustomize build deploy/overlays/local | grep -A1 'name: FAULTS_ENABLED'` → `value: "true"`.

### Task 3: Sekrety aplikacji w scripts/secrets.sh
**Commit:** feat(scripts): secrets.sh tworzy brakujące sekrety orders-api-token i fault-token

**Files:**
- Create: `scripts/secrets.sh`

1. Utwórz `scripts/secrets.sh` z poniższą treścią (bez bitu wykonywalnego, tak jak `doctor.sh`; Makefile woła `bash scripts/secrets.sh`):
   - `kubectl create` zamiast `apply`: `apply` zapisałby wartość jawnym tekstem w adnotacji `kubectl.kubernetes.io/last-applied-configuration`;
   - `fault-token` ma tę samą wartość w shop i loadgen: brakująca kopia dostaje wartość istniejącej, więc przerwane wcześniej uruchomienie nie rozjedzie tokenów;
   - wartość w cudzysłowie, bo YAML mógłby odczytać ciąg hex jako liczbę;
   - `set -e` przerywa skrypt przy błędzie API, bo odczyty są osobnymi przypisaniami, a nie warunkami.

```bash
#!/usr/bin/env bash
# Sekrety aplikacji z docs/architektura.md („Sekrety”), tworzone przy wdrożeniu (T04; grafana-admin dopisze T14).
# Uruchamiaj przez `make secrets` (krok `make up`); argument: kontekst kubectl.
# Istniejących sekretów nie zmienia, więc wartości są stabilne między kolejnymi `make up`.
# Wartości z `openssl rand -hex 32` są tylko w zmiennych i w potoku do `kubectl create -f -`:
# nie trafiają na dysk, do argumentów procesów, do adnotacji last-applied ani na ekran. Zgodny z bash 3.2 (macOS).
set -euo pipefail

ctx=${1:?użycie: scripts/secrets.sh <kontekst kubectl>}

if ! command -v openssl >/dev/null 2>&1; then
  echo "Brak openssl: zainstaluj go i uruchom make doctor." >&2
  exit 1
fi

k() { kubectl --context "$ctx" "$@"; }

# Wartość klucza token z istniejącego sekretu; pusta, gdy nie ma sekretu albo klucza.
read_token() { # namespace nazwa
  k -n "$1" get secret "$2" --ignore-not-found \
    -o go-template='{{if .data.token}}{{.data.token | base64decode}}{{end}}'
}

# Tworzy Secret typu Opaque z kluczem token. Manifest idzie przez stdin; printf jest wbudowany w bash.
create_token_secret() { # namespace nazwa wartość
  printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: %s\n  namespace: %s\ntype: Opaque\nstringData:\n  token: "%s"\n' \
    "$2" "$1" "$3" | k create -f - >/dev/null
  echo "Secret $1/$2 utworzony."
}

# Secret z kluczem token o tej samej wartości we wszystkich podanych namespace'ach.
# Brakująca kopia dostaje wartość istniejącej, a gdy nie ma żadnej, nową z openssl.
ensure_token_secret() { # nazwa namespace...
  local name=$1 ns value="" existing
  shift
  for ns in "$@"; do
    value=$(read_token "$ns" "$name")
    if [ -n "$value" ]; then
      break
    fi
  done
  if [ -z "$value" ]; then
    value=$(openssl rand -hex 32)
  fi
  for ns in "$@"; do
    existing=$(k -n "$ns" get secret "$name" --ignore-not-found -o name)
    if [ -n "$existing" ]; then
      echo "Secret $ns/$name już istnieje."
    else
      create_token_secret "$ns" "$name" "$value"
    fi
  done
}

ensure_token_secret orders-api-token shop
ensure_token_secret fault-token shop loadgen
```

Akceptacja zadania:
- `bash -n scripts/secrets.sh` → kod 0;
- na działającym klastrze `kind-secure-k8s-aiops`:
  - `mise exec -- kubectl --context kind-secure-k8s-aiops apply -f deploy/base/namespaces.yaml`;
  - dwa razy `mise exec -- bash scripts/secrets.sh kind-secure-k8s-aiops`;
  - pierwsze uruchomienie wypisuje `Secret shop/orders-api-token utworzony.`, `Secret shop/fault-token utworzony.` i `Secret loadgen/fault-token utworzony.`;
  - drugie wypisuje te same trzy nazwy z `już istnieje.`;
  - żadne nie wypisuje 64-znakowego ciągu hex.

### Task 4: make doctor sprawdza Docker Buildx i openssl
**Commit:** feat(doctor): sprawdzanie Docker Buildx i openssl

**Files:**
- Modify: `scripts/doctor.sh`

1. W bloku `if [ "$docker_ok" -eq 1 ]; then` (linie ~93–104), po `fi` zamykającym sprawdzenie pamięci (linia ~101, tuż przed `else`), wstaw:

```bash
  # make images: Dockerfile'e usług używają BuildKit (RUN --mount), a docker build ma go tylko z Buildx.
  if buildx_out=$(docker buildx version 2>/dev/null); then
    ok "Docker Buildx $(printf '%s\n' "$buildx_out" | cut -d ' ' -f 2)"
  else
    fail "brak Docker Buildx (potrzebny do make images)" \
      "Linux: pakiet docker-buildx (Arch, Ubuntu) albo docker-buildx-plugin (repozytorium Dockera); macOS i Windows: aktualny Docker Desktop"
  fi
```

2. W gałęzi `else` tego bloku, po linii `  skip "pamięć dla Dockera (brak dostępu do Dockera)"`, dopisz `  skip "Docker Buildx (brak dostępu do Dockera)"`.
3. Przed linią `echo "== Limity inotify (kind) =="` wstaw (z pustą linią na końcu):

```bash
echo "== Inne narzędzia =="
if command -v openssl >/dev/null 2>&1; then
  ok "$(openssl version | cut -d ' ' -f 1-2) (make secrets)"
else
  fail "brak openssl (potrzebny do make secrets)" "zainstaluj openssl menedżerem pakietów systemu"
fi

```

Akceptacja zadania:
- `bash -n scripts/doctor.sh` → kod 0;
- `make doctor` na maszynie z Buildx wypisuje linie `[ OK ] Docker Buildx v…` i `[ OK ] OpenSSL … (make secrets)` (na macOS `LibreSSL …`).

### Task 5: Cele Makefile up, down, namespaces, secrets, images, deploy, status, urls, prometheus, alertmanager
**Commit:** feat(make): make up i down, obrazy :dev, wdrożenie overlayu local, status, urls i port-forward

**Files:**
- Modify: `Makefile`

1. Zastąp treść `Makefile` poniższą. Wcięcia receptur to tabulatory. Nagłówek z `export PATH`, `include`, `doctor`, `cluster` (z `--image` z Task 1), `hubble-ui` i `hubble-relay` są jak dotąd, tylko komentarz `doctor` jest nowy. Jeśli Makefile na gałęzi ma cele spoza tej listy (np. dodane przez inne scalone zadanie), zachowaj je bez zmian i dopisz do `.PHONY`.

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
# Obrazy budowane w projekcie (w deploy/base bez tagu; overlay local ustawia :dev).
IMAGE_REPO := ghcr.io/l3x1cn/secure-k8s-aiops
# Namespace'y z Deploymentami aplikacji (etykieta app.kubernetes.io/part-of=secure-k8s-aiops), na które czeka deploy.
APP_NAMESPACES := shop loadgen aiops intruder

.PHONY: doctor up down cluster namespaces secrets images deploy status urls hubble-ui hubble-relay prometheus alertmanager

# Sprawdza narzędzia z mise.toml, dostęp do Dockera bez sudo, pamięć Dockera, Docker Buildx, openssl i limity inotify.
doctor:
	@bash scripts/doctor.sh

# Cała platforma jedną komendą: klaster → namespace'y i sekrety → obrazy → aplikacje, na końcu adresy.
# Idempotentny: na działającym klastrze niczego nie zmienia ani nie restartuje.
# Charty platformy (kube-prometheus-stack od T16) dochodzą jako krok między secrets a images.
up:
	$(MAKE) --no-print-directory cluster
	$(MAKE) --no-print-directory secrets
	$(MAKE) --no-print-directory images
	$(MAKE) --no-print-directory deploy
	@$(MAKE) --no-print-directory urls

# Usuwa klaster kind razem ze wszystkim, co w nim działa; bez klastra też kończy się sukcesem.
# Obrazy :dev zostają w Dockerze, więc następne make up ich nie przebudowuje od zera.
down:
	kind delete cluster --name '$(CLUSTER_NAME)'

# Klaster kind z Cilium i Hubble. Idempotentny: istniejącego klastra nie tworzy ponownie,
# a helm upgrade --install doprowadza CRD i Cilium do wersji i digestów z platform/versions.env.
# Obraz węzłów: KIND_NODE_IMAGE z platform/versions.env (--image nadpisuje obraz wszystkich węzłów).
# CRD prometheus-operator (ServiceMonitor) muszą istnieć przed instalacją Cilium.
# Po Cilium stosuje NetworkPolicy Hubble (platform/cilium/hubble-networkpolicy.yaml): do Relay tylko z Hubble UI.
cluster:
	@if kind get clusters | grep -qx '$(CLUSTER_NAME)'; then \
		echo "Klaster $(CLUSTER_NAME) już istnieje."; \
	else \
		kind create cluster --name '$(CLUSTER_NAME)' --image '$(KIND_NODE_IMAGE)' --config platform/kind/cluster.yaml; \
	fi
	helm upgrade --install prometheus-operator-crds $(PROMETHEUS_OPERATOR_CRDS_CHART)@$(PROMETHEUS_OPERATOR_CRDS_CHART_DIGEST) \
		--version $(PROMETHEUS_OPERATOR_CRDS_VERSION) \
		--kube-context $(KUBE_CONTEXT) --namespace kube-system --wait
	helm upgrade --install cilium $(CILIUM_CHART)@$(CILIUM_CHART_DIGEST) \
		--version $(CILIUM_VERSION) \
		--kube-context $(KUBE_CONTEXT) --namespace kube-system \
		--values platform/cilium/values.yaml --wait --timeout 10m
	kubectl --context $(KUBE_CONTEXT) apply -f platform/cilium/hubble-networkpolicy.yaml
	cilium status --context $(KUBE_CONTEXT) --wait
	kubectl --context $(KUBE_CONTEXT) wait --for=condition=Ready nodes --all --timeout=5m
	@echo "Klaster gotowy. Hubble UI: make hubble-ui. Hubble CLI: make hubble-relay (osobny terminal), potem hubble observe."

# Namespace'y z etykietami Pod Security (deploy/base/namespaces.yaml); muszą istnieć przed sekretami i chartami.
namespaces:
	kubectl --context $(KUBE_CONTEXT) apply -f deploy/base/namespaces.yaml

# Sekrety aplikacji (scripts/secrets.sh): tworzy tylko brakujące; wartości nie trafiają na dysk ani na ekran.
secrets: namespaces
	@bash scripts/secrets.sh '$(KUBE_CONTEXT)'

# Obrazy :dev budowane z korzenia repozytorium (workspace uv) i ładowane do węzłów kind.
# --provenance=false: atestacja BuildKit w magazynie obrazów containerd psuje kind load (kubernetes-sigs/kind#3795).
images:
	docker build --provenance=false -f services/frontend/Dockerfile -t $(IMAGE_REPO)/frontend:dev .
	docker build --provenance=false -f services/orders/Dockerfile -t $(IMAGE_REPO)/orders:dev .
	docker build --provenance=false -f chaos/Dockerfile -t $(IMAGE_REPO)/fault-runner:dev .
	kind load docker-image --name '$(CLUSTER_NAME)' $(IMAGE_REPO)/frontend:dev $(IMAGE_REPO)/orders:dev $(IMAGE_REPO)/fault-runner:dev

# Overlay local (namespace'y i aplikacje) przez kustomize z mise.toml, jak walidacja manifestów w CI (T06),
# potem rollout Deploymentów aplikacji. Błąd kustomize daje pusty strumień, na którym kubectl apply też kończy się błędem.
deploy:
	kustomize build deploy/overlays/local | kubectl --context $(KUBE_CONTEXT) apply -f -
	@for ns in $(APP_NAMESPACES); do \
		kubectl --context $(KUBE_CONTEXT) -n $$ns rollout status deployment \
			-l app.kubernetes.io/part-of=secure-k8s-aiops --timeout=5m || exit 1; \
	done

# Stan platformy: węzły, release'y Helm i pody we wszystkich namespace'ach.
status:
	kubectl --context $(KUBE_CONTEXT) get nodes
	helm list --all-namespaces --kube-context $(KUBE_CONTEXT)
	kubectl --context $(KUBE_CONTEXT) get pods --all-namespaces

# Adresy z docs/architektura.md („Dostęp z hosta”); w nawiasie zadanie, które wdraża usługę.
urls:
	@echo "frontend      http://localhost:8080"
	@echo "Grafana       http://localhost:3000 (T16)"
	@echo "Mailpit UI    http://localhost:8025 (T19)"
	@echo "Hubble UI     make hubble-ui, potem http://localhost:12000"
	@echo "Hubble Relay  make hubble-relay, potem hubble observe (localhost:4245)"
	@echo "Prometheus    make prometheus, potem http://localhost:9090 (T16)"
	@echo "Alertmanager  make alertmanager, potem http://localhost:9093 (T16)"

# Hubble UI w przeglądarce: port-forward na localhost:12000, Ctrl+C kończy.
hubble-ui:
	cilium hubble ui --context $(KUBE_CONTEXT)

# Hubble Relay dla CLI: port-forward na localhost:4245 (domyślny adres hubble), Ctrl+C kończy.
# W osobnym terminalu: hubble observe --last 20
hubble-relay:
	cilium hubble port-forward --context $(KUBE_CONTEXT)

# Prometheus (T16) na localhost:9090: port-forward, Ctrl+C kończy.
# Usługi prometheus-operated i alertmanager-operated tworzy prometheus-operator niezależnie od nazwy release'u.
prometheus:
	kubectl --context $(KUBE_CONTEXT) -n monitoring port-forward svc/prometheus-operated 9090:9090

# Alertmanager (T16) na localhost:9093: port-forward, Ctrl+C kończy.
alertmanager:
	kubectl --context $(KUBE_CONTEXT) -n monitoring port-forward svc/alertmanager-operated 9093:9093
```

   Decyzje wpisane w recepturę (nie zmieniaj):
   - `up` woła kroki przez `$(MAKE)` po kolei, nie jako prerekwizyty, więc `make -j up` nie wykona ich równolegle. `secrets` ma prerekwizyt `namespaces`: sekrety potrzebują namespace'ów, a samodzielne `make secrets` też ma działać.
   - Bez globalnego `pipefail`: w `cluster` potok `kind get clusters | grep -qx` przy `pipefail` mógłby zwrócić błąd przez SIGPIPE. Błąd `kustomize build` i tak kończy `deploy` błędem (pusty strumień → `no objects passed to apply`).
   - `kubectl rollout status -l` dla namespace'u bez Deploymentów (dziś aiops, intruder) wypisuje `No resources found in <ns> namespace.` i nie przerywa. Lista obejmuje je od razu, żeby T12/T24 nie musiały jej zmieniać.
   - `make prometheus` i `make alertmanager` do czasu T16 kończą się błędem `services "prometheus-operated" not found` (odpowiednio `alertmanager-operated`). Nie dodawaj sprawdzeń ani komunikatów zastępczych.
   - Obrazy bazowe Dockerfile'ów zostają przypięte w Dockerfile'ach (T05/T08), bo czyta je `docker build`, a nie Makefile. `versions.env` obejmuje to, czego używa Makefile: charty i obraz węzła kind.

Akceptacja zadania:
- `make -n up` wypisuje po kolei:
  - `kind create cluster …` (wewnątrz `if`),
  - `helm upgrade --install prometheus-operator-crds …`,
  - `helm upgrade --install cilium …`,
  - `kubectl … apply -f platform/cilium/hubble-networkpolicy.yaml`,
  - `cilium status …`,
  - `kubectl … wait … nodes …`,
  - `kubectl --context kind-secure-k8s-aiops apply -f deploy/base/namespaces.yaml`,
  - `bash scripts/secrets.sh 'kind-secure-k8s-aiops'`,
  - trzy `docker build --provenance=false …`,
  - `kind load docker-image --name 'secure-k8s-aiops' …` z trzema obrazami `:dev`,
  - `kustomize build deploy/overlays/local | kubectl --context kind-secure-k8s-aiops apply -f -`,
  - pętlę `rollout status`,
  - siedem linii `echo` z `urls`.
- `make up` na działającym klastrze T03 → kod 0. Log zawiera `deployment "frontend" successfully rolled out`, `deployment "orders" successfully rolled out` i `deployment "fault-runner" successfully rolled out`. Na końcu jest siedem linii adresów. `curl -fsS localhost:8080/healthz` → `{"status":"ok"}`.

### Task 6: Dokumentacja wdrożenia i czas make up
**Commit:** docs: wdrożenie make up/down, sekrety i dostęp z hosta (T04)

**Files:**
- Modify: `README.md`
- Modify: `docs/architektura.md`

1. Pomiar czasu (wymaga Dockera i wolnych portów 8080, 3000, 8025 poza samym klastrem): w korzeniu repo uruchom

```bash
mkdir -p reports
make down && start=$(date +%s) && make up > reports/t04-czas-up.log 2>&1 && echo "make up: $(( ($(date +%s) - start + 59) / 60 )) min"
```

   → kod 0 i liczba minut `N` (zaokrąglona w górę). Zanotuj `nproc` (`C`) i `free -g | awk '/^Mem:/ {print $2}'` (`M`). Gdy `make up` się nie powiedzie, wróć do sekcji „Assumptions & contingencies” i nie wpisuj czasu.
2. `README.md`, sekcja „Wymagania”:
   - w podpunkcie `**Linux:** Docker Engine. …` na końcu dopisz zdanie `` `make images` wymaga Docker Buildx: pakiet `docker-buildx` (Arch, Ubuntu) albo `docker-buildx-plugin` (repozytorium Dockera). ``;
   - linię `- [mise](https://mise.jdx.dev/getting-started.html) 2026.10.13 lub nowsze, git, GNU make, bash.` zmień na `- [mise](https://mise.jdx.dev/getting-started.html) 2026.10.13 lub nowsze, git, GNU make, bash, openssl.`
3. `README.md`, sekcja „Przygotowanie środowiska”: komentarz w linii `make doctor    # narzędzia, Docker bez sudo, pamięć Dockera, limity inotify` zmień na `# narzędzia, Docker bez sudo, pamięć Dockera, Docker Buildx, openssl, limity inotify`.
4. `README.md`: zastąp całą sekcję `## Klaster lokalny` (od nagłówka do następnego nagłówka `##`) poniższą treścią, z wartościami `N`, `C`, `M` z kroku 1:

````markdown
## Klaster lokalny

```bash
make up      # cała platforma: kind z Cilium i Hubble, namespace'y, sekrety, obrazy :dev, aplikacje
make status  # węzły, release'y Helm i pody
make urls    # adresy usług na hoście
make down    # usuwa klaster razem ze wszystkim, co w nim działa
```

`make up` od zera trwa ok. N min (maszyna R1: C CPU, M GB RAM, obrazy bazowe w cache Dockera). Ponowne `make up` na działającym klastrze niczego nie zmienia. Klaster kind `secure-k8s-aiops` ma kontekst kubectl `kind-secure-k8s-aiops`. Porty 8080, 3000 i 8025 na `127.0.0.1` muszą być wolne. Frontend: http://localhost:8080.

Kroki `make up` w tej kolejności; każdy działa też osobno:

```bash
make cluster  # kind (control-plane + 2 workery) z Cilium i Hubble
make secrets  # namespace'y i brakujące sekrety; wartości nie trafiają na dysk ani na ekran
make images   # obrazy :dev frontend, orders i fault-runner, załadowane do kind
make deploy   # overlay deploy/overlays/local; czeka na gotowość Deploymentów
```

Tag `:dev` się nie zmienia, więc po zmianie kodu usługi: `make images`, potem `kubectl -n <namespace> rollout restart deployment/<nazwa>`.

Port-forward (Ctrl+C kończy):

```bash
make hubble-ui     # Hubble UI: http://localhost:12000
make hubble-relay  # Hubble Relay na localhost:4245; w drugim terminalu: hubble observe --last 20
make prometheus    # Prometheus (od T16): http://localhost:9090
make alertmanager  # Alertmanager (od T16): http://localhost:9093
```
````

5. `README.md`, sekcja „Usługi” (z T05): na końcu akapitu zaczynającego się od `` Manifesty są w `deploy/base/ `` dopisz zdanie `` Do klastra obrazy `:dev` buduje i ładuje `make images` (krok `make up`). `` Gdy takiego akapitu nie ma, pomiń ten krok.
6. `docs/architektura.md`, tabela „Komponenty i wersje”, wiersz kind (linia ~9): po kodzie obrazu węzła dopisz `` (`KIND_NODE_IMAGE` w `platform/versions.env`) ``, a w kolumnie zadania zamień `T03` na `T03, T04`.
7. `docs/architektura.md`, sekcja „Namespace'y i Pod Security”: po tabeli (po wierszu `| kube-system | … |`) wstaw pustą linię i akapit:

```markdown
Namespace'y opisuje `deploy/base/namespaces.yaml` (T04); `make up` stosuje go przed sekretami i chartami. Etykieta `pod-security.kubernetes.io/enforce` odpowiada tabeli, a `warn`, `audit` i test dodaje T13.
```

8. `docs/architektura.md`, sekcja „Dostęp z hosta”:
   - akapit `` Klaster kind `secure-k8s-aiops` (kontekst kubectl `kind-secure-k8s-aiops`) tworzy `make cluster` (T03). `` zastąp akapitem `` Klaster kind `secure-k8s-aiops` (kontekst kubectl `kind-secure-k8s-aiops`) tworzy `make cluster` (T03). Całą platformę stawia `make up`, a usuwa `make down` (T04); `make urls` wypisuje adresy z tabeli. ``;
   - ostatni wiersz tabeli zastąp wierszem `` | `make hubble-ui`, `make hubble-relay`, `make prometheus`, `make alertmanager` | Hubble UI (localhost:12000), Hubble CLI (relay, localhost:4245), Prometheus (localhost:9090), Alertmanager (localhost:9093) | port-forward | ``;
   - po tabeli wstaw pustą linię i akapit `` `make prometheus` i `make alertmanager` łączą się z usługami `prometheus-operated` i `alertmanager-operated` w monitoring, które prometheus-operator (T16) tworzy niezależnie od nazwy release'u. ``
9. `docs/architektura.md`, sekcja „Sekrety”: zdanie `` Sekrety tworzy `make secrets` (T14) i nigdy nie trafiają do git. `` zastąp akapitem:

```markdown
Sekrety tworzy `make secrets` (`scripts/secrets.sh`, krok `make up`): tylko brakujące, z `openssl rand -hex 32`, bez zapisu wartości na dysk i bez wypisywania; nigdy nie trafiają do git. `orders-api-token` i `fault-token` (ta sama wartość w shop i loadgen) skrypt tworzy od T04, `grafana-admin` dochodzi w T14.
```

10. `docs/architektura.md`, sekcja „Struktura repozytorium”:
    - linię Makefile zastąp `├── Makefile               # doctor (T02); cluster, hubble-ui, hubble-relay (T03); up, down, namespaces, secrets, images, deploy, status, urls, prometheus, alertmanager (T04); test, report (dalej)` (zamyka DOC-001 z review T03);
    - linię `scripts/` zastąp `├── scripts/               # doctor.sh (T02), secrets.sh (T04, T14) i skrypty pomocnicze`.

Akceptacja zadania:
- `grep -n 'od zera trwa ok\.' README.md` zwraca jedną linię z liczbą minut;
- `grep -c 'make up' docs/architektura.md` ≥ 3;
- w README nie ma już `kind delete cluster --name secure-k8s-aiops`;
- każda kotwica z kroków 2–10 występuje dosłownie (oprócz kroku 5, który ma regułę pominięcia). Brak którejś: zatrzymaj się i zgłoś, którego tekstu nie ma.

## Critical files & anchors

- `Makefile`: Task 1 zmienia linię `kind create cluster` w `cluster`, Task 5 podaje pełną treść. `include platform/versions.env` musi zostać przed użyciem `$(KIND_NODE_IMAGE)`.
- `deploy/base/orders/deployment.yaml` i `deploy/base/frontend/service.yaml` (z #39/#40): cele patchy overlayu. Kontener `orders` ze zmienną `FAULTS_ENABLED`; port Service `name: http`, `port: 8080` jest kluczem scalania dla `nodePort`.
- `docs/architektura.md`: wiersz kind (~9), „Namespace'y i Pod Security” (~29–38), „Dostęp z hosta” (~40–51), „Sekrety” (~122–124), „Struktura repozytorium” (Makefile ~151, scripts ~165); numery linii przesuną się po scaleniu #39/#40, więc kotwiczą cytowane zdania.
- `scripts/doctor.sh` linie ~93–112: blok Dockera i początek sekcji inotify (Task 4).

## Verification

Warunki wstępne:
- katalog roboczy to korzeń repo na gałęzi delivery;
- `docker info` i `docker buildx version` działają bez sudo;
- porty 8080, 3000 i 8025 na `127.0.0.1` są wolne albo zajmuje je tylko istniejący klaster kind (`docker port secure-k8s-aiops-control-plane`), który usunie `make down`. Na maszynie R1 port 8080 zajmował kiedyś llama.cpp: właściciel zatrzymuje go na czas weryfikacji, mapowań portów nie zmieniamy;
- porty 9090 i 9093 są wolne;
- jedna sesja bash z `set -o pipefail`, `mkdir -p reports`, `K="mise exec -- kubectl --context kind-secure-k8s-aiops"`.

Czas: ok. 25 min (trzy pełne `make up`).

1. `make doctor` → kod 0. Wynik zawiera `[ OK ] Docker Buildx v…` i `[ OK ] OpenSSL … (make secrets)`, a ostatnia linia to `Wszystkie sprawdzenia przeszły.`
2. Manifesty:
   - `mise exec -- kustomize build deploy/overlays/local | mise exec -- kubeconform -strict -summary -` → `Valid: 10, Invalid: 0, Errors: 0, Skipped: 0`;
   - `mise exec -- kustomize build deploy/base | mise exec -- kubeconform -strict -summary -` → `Invalid: 0, Errors: 0`.
3. Kolejność kroków: `make -n up` wypisuje polecenia w kolejności z akceptacji Task 5.
4. Kryterium 1, przebieg 1 (na końcu drugi `make down` sprawdza, że `down` bez klastra też kończy się kodem 0):

```bash
make down && make down
TIMEFORMAT='make up (przebieg 1): %0R s'
{ time make up 2>&1 | tee reports/t04-up-1.log; } 2>> reports/t04-czasy.txt
$K wait --for=condition=Ready pod --all -A --timeout=120s
curl -fsS -w ' %{http_code}\n' http://localhost:8080/healthz | tee -a reports/t04-healthz.txt
```

   Oczekiwane wyniki:
   - oba `make down` i `make up` kończą się kodem 0;
   - `reports/t04-up-1.log` zawiera trzy linie `successfully rolled out` (frontend, orders, fault-runner) oraz linie `Image: "ghcr.io/l3x1cn/secure-k8s-aiops/<nazwa>:dev" …` bez `ERROR` i kończy się siedmioma liniami `make urls`;
   - `kubectl wait` wypisuje `condition met` dla każdego poda;
   - `curl` zwraca `{"status":"ok"} 200`.

   Przebieg 2: te same polecenia z jednym `make down`, `TIMEFORMAT='make up (przebieg 2): %0R s'` i logiem `reports/t04-up-2.log`, z tym samym oczekiwanym wynikiem. Potem `$K get pods -A -o wide > reports/t04-pody.txt`.
5. Kryterium 2 (idempotencja) na klastrze z przebiegu 2:

```bash
snap() {
  $K get pods -A --no-headers -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,UID:.metadata.uid,RESTARTS:.status.containerStatuses[*].restartCount'
  $K get deployments -A --no-headers -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,GEN:.metadata.generation'
  $K get namespaces shop loadgen aiops intruder monitoring --no-headers -o custom-columns='NAME:.metadata.name,RV:.metadata.resourceVersion'
  $K -n shop get services,secrets --no-headers -o custom-columns='KIND:.kind,NAME:.metadata.name,RV:.metadata.resourceVersion'
  $K -n loadgen get secrets --no-headers -o custom-columns='KIND:.kind,NAME:.metadata.name,RV:.metadata.resourceVersion'
}
snap | sort > reports/t04-przed.txt
make up 2>&1 | tee reports/t04-up-3.log
{ snap | sort | diff reports/t04-przed.txt - && echo "snapshot: bez zmian"; } | tee reports/t04-idempotencja.txt
grep -E '^[a-z.]+/[a-z0-9-]+ (created|configured)$' reports/t04-up-3.log
curl -fsS -w ' %{http_code}\n' http://localhost:8080/healthz | tee -a reports/t04-healthz.txt
```

   Oczekiwane wyniki:
   - `make up` → kod 0;
   - `reports/t04-idempotencja.txt` zawiera tylko `snapshot: bez zmian` (pody z tym samym UID i bez nowych restartów, te same generacje Deploymentów, te same wersje namespace'ów, usług i sekretów);
   - `grep` nic nie znajduje (kod 1): każde `kubectl apply` w logu kończy się `unchanged`;
   - log zawiera `Klaster secure-k8s-aiops już istnieje.` i trzy linie `Secret … już istnieje.`;
   - `curl` → `{"status":"ok"} 200`.

   Helm wypisuje `has been upgraded` (nowa rewizja release'u bez zmian w zasobach, jak w T03), a `kind load` może zaimportować obrazy ponownie (magazyn containerd). Snapshot pokazuje, że żadne z nich nie zmienia zasobów.
6. Overlay i wersje na żywym klastrze:
   - `$K -n shop get svc frontend -o jsonpath='{.spec.type} {.spec.ports[0].nodePort}{"\n"}'` → `NodePort 30080`;
   - `$K get deploy -A -l app.kubernetes.io/part-of=secure-k8s-aiops -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.spec.template.spec.containers[0].image} {.spec.template.spec.containers[0].imagePullPolicy}{"\n"}{end}'` → `loadgen/fault-runner ghcr.io/l3x1cn/secure-k8s-aiops/fault-runner:dev IfNotPresent`, `shop/frontend ghcr.io/l3x1cn/secure-k8s-aiops/frontend:dev IfNotPresent`, `shop/orders ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev IfNotPresent`;
   - `$K get ns shop loadgen aiops intruder monitoring -L pod-security.kubernetes.io/enforce` → `restricted` dla czterech pierwszych, `privileged` dla monitoring;
   - `docker inspect -f '{{.Name}} {{.Config.Image}}' secure-k8s-aiops-control-plane secure-k8s-aiops-worker secure-k8s-aiops-worker2` → trzy razy `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`.
7. Ścieżki aplikacji (wynik dopisuj do `reports/t04-aplikacje.txt` przez `| tee -a`):
   - `curl -fsS -X POST http://localhost:8080/order -H 'Content-Type: application/json' -d '{"product_id":"kubek","quantity":1}' -w ' %{http_code}\n'` → JSON z `"product_id":"kubek"` i ` 201`. Frontend przechodzi do orders z tokenem z `orders-api-token`.
   - `$K -n loadgen exec deploy/fault-runner -- fault-runner fault errors --seconds 5 --param ratio=0.5` → linia z `"fault":"errors"`, kod 0. Bez `FAULTS_ENABLED=true` byłoby 404, a przy różnych `fault-token` w shop i loadgen 403; w obu przypadkach kod 1.
   - Potem `$K -n loadgen exec deploy/fault-runner -- fault-runner stop` → linia z `"stopped"`, kod 0.
8. Sekrety (wynik dopisuj do `reports/t04-sekrety.txt`, bez wartości):

```bash
$K -n shop get secret orders-api-token -o go-template='{{.data.token | base64decode | len}}{{"\n"}}'
same() { cmp -s <($K -n shop get secret fault-token -o go-template='{{.data.token}}') <($K -n loadgen get secret fault-token -o go-template='{{.data.token}}') && echo "fault-token: zgodne"; }
same
$K -n shop get secret orders-api-token fault-token -o jsonpath='{range .items[*]}{.metadata.name}:{.metadata.annotations}{"\n"}{end}'
$K -n loadgen delete secret fault-token
make secrets 2>&1 | tee reports/t04-secrets.log
same
grep -E '[0-9a-f]{64}' reports/t04-secrets.log reports/t04-up-*.log
```

   Oczekiwane wyniki:
   - pierwsze polecenie → `64`;
   - `same` → `fault-token: zgodne` (oba razy);
   - adnotacje → `orders-api-token:` i `fault-token:` bez treści po dwukropku;
   - `reports/t04-secrets.log` zawiera `Secret shop/orders-api-token już istnieje.`, `Secret shop/fault-token już istnieje.` i `Secret loadgen/fault-token utworzony.`;
   - ostatni `grep` nic nie znajduje (kod 1).
9. `make status` → kod 0. Wynik pokazuje trzy węzły `Ready`, release'y `cilium` i `prometheus-operator-crds` ze statusem `deployed` oraz pody shop i loadgen `Running`. `make urls` → siedem linii, od `frontend      http://localhost:8080` do `Alertmanager  make alertmanager, potem http://localhost:9093 (T16)`.
10. Port-forward `make prometheus` i `make alertmanager` (Prometheus i Alertmanager przyjdą z T16; tu atrapa usług o tych nazwach):

```bash
$K -n monitoring run pf-smoke --image=ghcr.io/l3x1cn/secure-k8s-aiops/frontend:dev --image-pull-policy=IfNotPresent --env=ORDERS_API_TOKEN=smoke --port=8080
$K -n monitoring wait --for=condition=Ready pod/pf-smoke --timeout=2m
$K -n monitoring expose pod pf-smoke --name=prometheus-operated --port=9090 --target-port=8080
$K -n monitoring expose pod pf-smoke --name=alertmanager-operated --port=9093 --target-port=8080
make prometheus > reports/t04-pf-prometheus.log 2>&1 & P1=$!
make alertmanager > reports/t04-pf-alertmanager.log 2>&1 & P2=$!
sleep 5
curl -fsS http://localhost:9090/healthz; echo
curl -fsS http://localhost:9093/healthz; echo
kill $P1 $P2; pkill -f 'port-forward svc/(prometheus|alertmanager)-operated' || true
$K -n monitoring delete pod/pf-smoke service/prometheus-operated service/alertmanager-operated
```

   → oba `curl` zwracają `{"status":"ok"}`; `delete` usuwa trzy obiekty. Klaster zostaje włączony.

## Po dostarczeniu: issue i PR

Wykonuje główny agent po przejściu Verification i code review bez CRITICAL/HIGH. Konto `gh`: `l3x1cn` (zalogowane, scope `repo`, git używa `gh auth git-credential`). `B=$(git branch --show-current)`.

1. `git push -u origin "$B"`.
2. Reguła Helm w opisie #4 (MAINT-001 z drugiego review T03): `gh issue view 4 --repo l3x1cn/secure-k8s-aiops --json body --jq .body > reports/t04-body.md`. W tym pliku zamień linię

```markdown
- Każda instalacja Helm: `helm upgrade --install --wait --version <z versions.env>` z plikiem values w repozytorium.
```

   na

```markdown
- Każda instalacja Helm: `helm upgrade --install --wait <chart>@<*_CHART_DIGEST> --version <*_VERSION>` (oba z `platform/versions.env`); ustawienia chartu w pliku values w repozytorium, bez `--set`; chart bez zmienionych ustawień (np. `prometheus-operator-crds`) nie ma pliku values.
```

   potem `gh issue edit 4 --repo l3x1cn/secure-k8s-aiops --body-file reports/t04-body.md` → `gh issue view 4` pokazuje nową linię. Checkboxów w issue nie zaznaczaj; zaznaczone są w opisie PR, tak jak w T03.
3. Komentarz z dowodem w #4: zbuduj `reports/t04-dowod.md`:

```bash
noansi() { sed -r 's/\x1B\[[0-9;]*[A-Za-z]//g' "$1"; }
{
  echo "## Dowód kryteriów akceptacji T04"; echo
  echo "Gałąź \`$B\`, commit \`$(git rev-parse --short HEAD)\`; kind 0.33.0 (Kubernetes 1.36.4), Cilium 1.20.3, Docker $(docker version --format '{{.Server.Version}}'), $(nproc) CPU."; echo
  echo "### 1. \`make down && make up\` od zera, dwa razy z rzędu"; echo
  echo '```text'; cat reports/t04-czasy.txt reports/t04-healthz.txt; echo '```'; echo
  echo "Pody po drugim przebiegu:"; echo; echo '```text'; cat reports/t04-pody.txt; echo '```'; echo
  echo "Koniec logu drugiego przebiegu:"; echo; echo '```text'; noansi reports/t04-up-2.log | tail -n 60; echo '```'; echo
  echo "### 2. Ponowne \`make up\` na działającym klastrze"; echo
  echo '```text'; cat reports/t04-idempotencja.txt; grep -E ' unchanged$|już istnieje\.$' reports/t04-up-3.log; echo '```'; echo
  echo "### Ścieżki aplikacji i sekrety"; echo
  echo '```text'; cat reports/t04-aplikacje.txt reports/t04-sekrety.txt; echo '```'
} > reports/t04-dowod.md
gh issue comment 4 --repo l3x1cn/secure-k8s-aiops --body-file reports/t04-dowod.md
```

   → zapisz URL komentarza.
4. PR: `gh pr create --repo l3x1cn/secure-k8s-aiops --base main --head "$B" --title "T04 · Powtarzalne wdrożenie: make up/down, Kustomize, namespace'y" --body-file reports/t04-pr.md`. Plik `reports/t04-pr.md` ma poniższą treść; wstaw URL z kroku 3 i oba czasy z `reports/t04-czasy.txt`:

```markdown
Closes #4

- `make up`: klaster kind z Cilium i Hubble (`make cluster`) → namespace'y i sekrety (`make secrets`) → obrazy `:dev` (`make images`) → overlay `local` (`make deploy`) → adresy (`make urls`). Idempotentny; `make down` usuwa klaster.
- `platform/versions.env`: nowy `KIND_NODE_IMAGE` (`kind create cluster --image`); `platform/kind/cluster.yaml` bez obrazów.
- `deploy/base/namespaces.yaml`: shop, loadgen, aiops, intruder (`enforce: restricted`), monitoring (`enforce: privileged`); `warn`, `audit` i test zostają w T13.
- `deploy/overlays/local`: obrazy `:dev`, `imagePullPolicy: IfNotPresent`, frontend na NodePort 30080 (localhost:8080), `FAULTS_ENABLED=true` w orders.
- `scripts/secrets.sh` (`make secrets`): brakujące `orders-api-token` i `fault-token` (ta sama wartość w shop i loadgen) z `openssl rand -hex 32`, przez stdin do `kubectl create`; wartości nie trafiają na dysk ani na ekran. T14 dopisze `grafana-admin`.
- `make images`: `docker build --provenance=false`, bo atestacje BuildKit w magazynie obrazów containerd psują `kind load` (kubernetes-sigs/kind#3795).
- `make status`, `make urls`, `make prometheus` (localhost:9090) i `make alertmanager` (localhost:9093) przez `svc/prometheus-operated` i `svc/alertmanager-operated` (działają od T16).
- `make doctor` sprawdza Docker Buildx i openssl.
- Dokumentacja: README („Klaster lokalny”, czas `make up`), `docs/architektura.md` (namespace'y, dostęp z hosta, sekrety, struktura repozytorium).

Zamknięte uwagi z review T03: MAINT-001 (obraz węzła kind poza `versions.env`), DOC-001 (mapa repozytorium), MAINT-001 z drugiego review (reguła Helm w opisie #4 zaktualizowana).

Kryteria akceptacji, dowód: <URL komentarza>
- [x] `make down && make up` od zera dwa razy z rzędu: wszystkie pody Ready, `/healthz` 200 (czasy: <czas 1>, <czas 2>); czas `make up` w README.
- [x] Ponowne `make up` na działającym klastrze: pody, Deploymenty, namespace'y, usługi i sekrety bez zmian; każde `kubectl apply` → `unchanged`.
- [ ] Ten sam wynik na drugiej maszynie: @DreadGoblin, proszę o `make down && make up` na tej gałęzi i komentarz z czasem i wynikiem `make status`.
```

   → `gh pr view --repo l3x1cn/secure-k8s-aiops "$B" --json state,baseRefName,headRefName` → `OPEN`, `main`, `$B`.

## Assumptions & contingencies

Założenia (właściciel może je zmienić):
- T04 dostarcza tylko te sekrety, których potrzebują wdrażane pody (`orders-api-token`, `fault-token`). `grafana-admin`, `make grafana-password`, pre-commit i `tests/security/test_secrets.py` zostają w T14.
- `make urls` wypisuje wszystkie adresy z kontraktu „Dostęp z hosta”, z numerem zadania przy usługach, których jeszcze nie ma.
- PR jest gotowy do review (nie draft). Kryterium 3 domyka drugi członek zespołu po utworzeniu PR.

Plan awaryjny:
- Treść z #39/#40 na `main` różni się od opisanej w „Ustalone fakty” (inne nazwy obrazów, kontenera `orders`, portu `http` albo podkatalogów): w overlayu i Makefile użyj nazw z `main`, a reszty planu nie zmieniaj. Gdy na `main` nie ma `deploy/base/kustomization.yaml` albo któregoś Deploymentu, zatrzymaj się i zgłoś to właścicielowi.
- `docker build` kończy się błędem `unknown flag: --provenance` albo `the --mount option requires BuildKit`: brakuje Docker Buildx (`make doctor` pokazuje FAIL). Zatrzymaj się; Buildx instaluje właściciel.
- `docker` zwraca `permission denied`: powłoka nie ma grupy `docker`. Zatrzymaj się; właściciel loguje się ponownie.
- `kind load docker-image` mimo `--provenance=false` kończy się błędem `mismatched image rootfs and manifest layers` albo `content digest … not found`: zatrzymaj się i zgłoś pełny komunikat oraz wynik `docker image inspect ghcr.io/l3x1cn/secure-k8s-aiops/frontend:dev --format '{{json .Descriptor}}'`. Nie zmieniaj ustawień magazynu obrazów Dockera.
- `make deploy` przekracza `--timeout=5m`: sprawdź `$K get pods -A` i `$K describe pod`.
  - `CreateContainerConfigError` → brak sekretu: uruchom `make secrets`, potem `make deploy`.
  - `ErrImagePull` albo `ImagePullBackOff` dla `:dev` → obrazy nie są w węzłach: uruchom `make images`, potem `make deploy`.
  - Inna przyczyna albo powtórzony błąd → zatrzymaj się i zgłoś wynik `describe`. Nie podnoś timeoutu.
- `kind create cluster` kończy się błędem `address already in use` albo `port is already allocated`: zwolnij port (8080 na maszynie R1 → właściciel zatrzymuje llama.cpp) i uruchom `make up` ponownie. Gdy `kind get clusters` pokazuje `secure-k8s-aiops` bez działających węzłów, najpierw `make down`.
- Snapshot z kroku 5 Verification pokazuje zmiany: zapisz diff. Jeśli zmieniły się zasoby Helm w kube-system, zgłoś właścicielowi, który release je zmienia. Nie dodawaj warunkowego pomijania `helm upgrade` bez jego decyzji. Zmiany w shop i loadgen to błąd T04: popraw przyczynę i powtórz krok 5.
- `kubeconform` zgłasza inną liczbę zasobów niż 10, bo inne scalone zadanie dodało zasoby do `deploy/base`: wymagane jest `Invalid: 0, Errors: 0`, a `Valid` równe liczbie obiektów z `kustomize build`.
