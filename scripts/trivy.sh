#!/usr/bin/env bash
# Bramka Trivy (T15): jeden skan obrazu albo katalogu deploy/ Trivy z mise.toml. Wyniki ze wszystkimi poziomami
# trafiają do reports/trivy/: <cel>.json (raport testów, T31) i <cel>.sarif (GitHub code scanning, job sarif w CI).
# Bramka to `--severity HIGH,CRITICAL --exit-code 1` na wyniku skanu (`trivy convert`), a obraz skanuje się
# z `--ignore-unfixed`, więc blokują tylko podatności z dostępną poprawką. Log pokazuje tabelę tego, co blokuje.
# Kod 1: znalezisko HIGH albo CRITICAL, błąd skanu albo .trivyignore niezgodny z regułą poniżej; kod 2: złe argumenty.
# Użycie:
#   make trivy-config                             # = scripts/trivy.sh config; job manifests w ci.yml
#   bash scripts/trivy.sh image <nazwa> <obraz>   # obraz z lokalnego Dockera (--image-src docker); joby build
#                                                 # i push w images.yml, lokalnie np. po make images:
#                                                 # bash scripts/trivy.sh image orders ghcr.io/l3x1cn/secure-k8s-aiops/orders:dev
# .trivyignore (korzeń repozytorium; Trivy czyta go z bieżącego katalogu): każdy wpis stoi w grupie pod komentarzem
# z uzasadnieniem (bez pustej linii między komentarzem a wpisami) i kończy się datą przeglądu exp:RRRR-MM-DD.
# Po tej dacie Trivy przestaje stosować wpis, więc bramka znów zgłasza znalezisko.
# Zgodny z bash 3.2 (macOS).
set -euo pipefail

cd "$(dirname "$0")/.."

# Trivy i yq w wersjach z mise.toml mają pierwszeństwo przed systemowymi, także bez make i bez aktywacji mise
# w powłoce (jak PATH w Makefile).
PATH="$(mise bin-paths 2>/dev/null | tr '\n' ':' || true)$PATH"

out=reports/trivy

usage() {
  echo "Użycie: $0 config | image <nazwa> <obraz>" >&2
  exit 2
}

# Reguła .trivyignore (T15): linia wpisu musi należeć do grupy otwartej komentarzem (pusta linia zamyka grupę)
# i kończyć się exp:RRRR-MM-DD. Wypisuje każde naruszenie z numerem linii; kod 1, gdy jest choć jedno.
check_ignorefile() {
  [ -f .trivyignore ] || return 0
  awk '
    /^[ \t]*$/ { group = 0; next }
    /^[ \t]*#/ { group = 1; next }
    {
      if (!group || $0 !~ /[ \t]exp:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9][ \t]*$/) {
        printf ".trivyignore:%d: wpis bez komentarza z uzasadnieniem nad grupą albo bez exp:RRRR-MM-DD: %s\n", NR, $0 > "/dev/stderr"
        bad = 1
      }
    }
    END { exit bad }
  ' .trivyignore
}

[ $# -ge 1 ] || usage
case $1 in
  config)
    [ $# -eq 1 ] || usage
    name=config
    target=deploy/
    scanners=misconfig
    ;;
  image)
    [ $# -eq 3 ] || usage
    name=image-$2
    target=$3
    scanners=vuln,secret
    ;;
  *)
    usage
    ;;
esac

if ! check_ignorefile; then
  echo "Popraw .trivyignore według reguły z jego nagłówka." >&2
  exit 1
fi

mkdir -p "$out"
json=$out/$name.json
sarif=$out/$name.sarif
# Stary wynik z poprzedniego uruchomienia nie może udawać nowego.
rm -f "$json" "$sarif"

# Skan bez filtra poziomów i bez --exit-code: każdy kod różny od 0 to błąd Trivy (set -e kończy skrypt).
# --skip-version-check: bez zapytania o nowszą wersję (wersję wyznacza mise.toml).
if [ "$1" = config ]; then
  trivy config --skip-version-check --format json --output "$json" "$target"
else
  trivy image --skip-version-check --image-src docker --no-progress --ignore-unfixed --format json --output "$json" "$target"
fi

trivy convert --quiet --format sarif --output "$sarif" "$json"
if [ "$1" = config ]; then
  # Trivy podaje ścieżki względem deploy/ z uriBaseId, a code scanning czyta uri względem korzenia repozytorium
  # i pomija uriBaseId (github/codeql-action#2215): bez prefiksu alert wskazuje nieistniejący plik.
  yq -i -p json -o json '(.runs[].results[].locations[].physicalLocation.artifactLocation.uri) |= "deploy/" + . | del(.runs[].originalUriBaseIds) | del(.runs[].results[].locations[].physicalLocation.artifactLocation.uriBaseId)' "$sarif"
fi

if ! trivy convert --quiet --scanners "$scanners" --severity HIGH,CRITICAL --exit-code 1 --format table "$json"; then
  echo "BŁĄD: bramka Trivy: znaleziska HIGH albo CRITICAL w $target (tabela wyżej). Wyniki: $json, $sarif." >&2
  exit 1
fi
echo "Bramka Trivy: $target bez znalezisk HIGH i CRITICAL. Wyniki: $json, $sarif."
