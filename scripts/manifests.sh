#!/usr/bin/env bash
# Walidacja manifestów (T06): `kustomize build` każdego overlayu z deploy/overlays → `kubeconform -strict`,
# a spec każdego PrometheusRule z tego wyniku → `promtool check rules` (T19; yq wycina spec do osobnego pliku).
# Uruchamiaj przez `make manifests` (to samo robi job manifests w CI). Sprawdza wszystkie overlaye, czyli katalogi
# z kustomization.yaml (nowy overlay, np. cloud z T29, wchodzi automatycznie), i kończy się kodem 1, gdy któryś
# się nie buduje, ma zasób niezgodny ze schematem, nie ma żadnego PrometheusRule albo któraś reguła nie przechodzi
# promtool. Zgodny z bash 3.2 (macOS).
# Schematy: Kubernetes w wersji węzłów kind (KIND_NODE_IMAGE z platform/versions.env) z yannh/kubernetes-json-schema
# i CRD z datreeio/CRDs-catalog; obie lokalizacje przypięte po commicie, więc wynik nie zależy od zmian upstreamu.
# Zasób bez schematu to błąd: kubeconform działa bez -ignore-missing-schemas.
set -euo pipefail

cd "$(dirname "$0")/.."

# Schematy podstawowe: yannh/kubernetes-json-schema, commit z 2026-11-05 (zawiera v1.36.4-standalone-strict).
# Brak schematu dla nowej wersji Kubernetes: podbij na nowszy commit z master.
K8S_SCHEMAS_COMMIT=102361970337d65537d40141dc29b991b8e95786
k8s_location="https://raw.githubusercontent.com/yannh/kubernetes-json-schema/$K8S_SCHEMAS_COMMIT/{{.NormalizedKubernetesVersion}}-standalone{{.StrictSuffix}}/{{.ResourceKind}}{{.KindSuffix}}.json"

# datreeio/CRDs-catalog, commit z 2026-11-05. CRD bez schematu w tym commicie: podbij na nowszy commit z main.
CRDS_CATALOG_COMMIT=c86448cbf1a840ca62d119259864863897c8748a
crds_location="https://raw.githubusercontent.com/datreeio/CRDs-catalog/$CRDS_CATALOG_COMMIT/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"

. platform/versions.env
# kindest/node:v1.36.4@sha256:… → 1.36.4
k8s_version=${KIND_NODE_IMAGE#*:v}
k8s_version=${k8s_version%%@*}
case $k8s_version in
  '' | *[!0-9.]*)
    echo "Nie da się odczytać wersji Kubernetes z KIND_NODE_IMAGE=$KIND_NODE_IMAGE." >&2
    exit 1
    ;;
esac

rules_dir=$(mktemp -d)
trap 'rm -rf "$rules_dir"' EXIT

# Reguły z PrometheusRule w wyniku kustomize build ($1: overlay): promtool czyta plik z kluczem groups,
# czyli spec obiektu. Kod 1, gdy któraś reguła jest błędna albo overlay nie ma żadnej.
# set -e nie działa w funkcji wołanej w warunku (`elif ! check_rules`), stąd jawne `|| return 1`.
check_rules() {
  local overlay=$1 rule count=0
  rm -rf "${rules_dir:?}"/*
  kustomize build "$overlay" \
    | yq 'select(.kind == "PrometheusRule")' --split-exp "\"$rules_dir/\" + .metadata.namespace + \"-\" + .metadata.name" \
    || { echo "kustomize build | yq: błąd dla $overlay" >&2; return 1; }
  for rule in "$rules_dir"/*.yml; do
    [ -f "$rule" ] || continue
    count=$((count + 1))
    # -e: kod błędu, gdy spec jest puste (promtool przyjąłby pusty plik jako 0 reguł).
    yq -e '.spec' "$rule" >"${rule%.yml}.rules.yaml" || return 1
    echo "promtool: $(basename "${rule%.yml}")"
    promtool check rules "${rule%.yml}.rules.yaml" || return 1
  done
  if [ "$count" -eq 0 ]; then
    echo "Brak PrometheusRule w $overlay." >&2
    return 1
  fi
}

total=0
failed=0
for kustomization in deploy/overlays/*/kustomization.yaml; do
  [ -f "$kustomization" ] || continue
  overlay=${kustomization%/kustomization.yaml}
  total=$((total + 1))
  echo "== $overlay (Kubernetes $k8s_version)"
  # pipefail: nieudany kustomize build daje pusty strumień, który kubeconform uznałby za poprawny.
  if ! kustomize build "$overlay" | kubeconform -strict -summary \
    -kubernetes-version "$k8s_version" \
    -schema-location "$k8s_location" \
    -schema-location "$crds_location" \
    -; then
    echo "BŁĄD: $overlay" >&2
    failed=$((failed + 1))
  elif ! check_rules "$overlay"; then
    echo "BŁĄD (reguły Prometheusa): $overlay" >&2
    failed=$((failed + 1))
  fi
done

if [ "$total" -eq 0 ]; then
  echo "Brak overlayów: deploy/overlays/*/kustomization.yaml." >&2
  exit 1
fi
if [ "$failed" -gt 0 ]; then
  echo "Błędne overlaye: $failed z $total." >&2
  exit 1
fi
echo "Wszystkie overlaye poprawne ($total)."
