#!/usr/bin/env bash
# Walidacja manifestów (T06): `kustomize build` każdego overlayu z deploy/overlays → `kubeconform -strict`.
# Uruchamiaj przez `make manifests` (to samo robi job manifests w CI). Sprawdza wszystkie overlaye, czyli katalogi
# z kustomization.yaml (nowy overlay, np. cloud z T29, wchodzi automatycznie), i kończy się kodem 1, gdy któryś
# się nie buduje albo ma zasób niezgodny ze schematem. Zgodny z bash 3.2 (macOS).
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
