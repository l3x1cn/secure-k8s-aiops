#!/usr/bin/env bash
# Sekrety z docs/architektura.md („Sekrety”), tworzone przy wdrożeniu (T04; grafana-admin od T16, bo czyta go Grafana).
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

# Logowanie do Grafany (T16): użytkownik admin i losowe hasło; chart czyta klucze admin-user i admin-password.
if [ -n "$(k -n monitoring get secret grafana-admin --ignore-not-found -o name)" ]; then
  echo "Secret monitoring/grafana-admin już istnieje."
else
  # Osobne przypisanie: błąd openssl zatrzymuje skrypt (set -e) zamiast tworzyć Secret z pustym hasłem.
  password=$(openssl rand -hex 32)
  printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: grafana-admin\n  namespace: monitoring\ntype: Opaque\nstringData:\n  admin-user: admin\n  admin-password: "%s"\n' \
    "$password" | k create -f - >/dev/null
  echo "Secret monitoring/grafana-admin utworzony."
fi
