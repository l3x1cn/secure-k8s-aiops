#!/usr/bin/env bash
# Test mutacyjny NetworkPolicy (T26): bez polityki default-deny w shop musi paść test odmowy połączenia.
# Skrypt usuwa shop/default-deny, uruchamia tests/security/test_network_policies.py i wymaga, żeby padły (FAILED)
# dokładnie testy z EXPECTED_FAILED, żeby nie wystąpił żaden ERROR, a pozostałe przeszły. Potem przywraca politykę
# i wymaga zielonego przebiegu.
# Bez default-deny testy odmowy do frontend i orders nadal przechodzą: oba pody mają własne polityki ingress,
# a allow-dns izoluje egress każdego poda w shop. default-deny odcina pod bez własnej reguły, więc pada test
# z podem t26-unlisted i sprawdzenie samego obiektu polityki.
# Politykę przywraca kubectl apply pliku z deploy/base, także po błędzie i po Ctrl+C (pułapka EXIT). Overlay
# local nie zmienia NetworkPolicy, więc obiekt jest taki sam jak po make deploy.
# Logi obu przebiegów: reports/mutation-check/mutated.txt i reports/mutation-check/restored.txt.
# Kod 0: mutacja wykryta i polityka przywrócona; 1: mutacja przeżyła, inny wynik testów albo błąd;
# 130 i 143: przerwanie (Ctrl+C, SIGTERM), polityka przywrócona.
# Użycie: bash tests/security/mutation_check.sh (klaster z make up, ok. 3–4 min). Kontekst: zmienna
# KUBE_CONTEXT, domyślnie kind-secure-k8s-aiops, jak w Makefile i w testach.
# Zgodny z bash 3.2 (macOS).
set -euo pipefail

cd "$(dirname "$0")/../.."

# kubectl, hubble i uv w wersjach z mise.toml mają pierwszeństwo przed systemowymi, także bez make
# i bez aktywacji mise w powłoce (jak scripts/trivy.sh).
PATH="$(mise bin-paths 2>/dev/null | tr '\n' ':' || true)$PATH"

export KUBE_CONTEXT="${KUBE_CONTEXT:-kind-secure-k8s-aiops}"
POLICY=deploy/base/networkpolicies/default-deny.yaml
TESTS=tests/security/test_network_policies.py
# Identyfikatory z linii FAILED podsumowania pytest (-rfE), jeden w linii. Linia ERROR (np. błąd fixture
# poda próbnego) nie jest wykryciem mutacji.
EXPECTED_FAILED="$TESTS::test_intruder_to_unlisted_pod_is_denied[shop]
$TESTS::test_namespace_has_default_deny[shop]"
# Cilium potrzebuje chwili na zmianę polityk (jak sleep 10 w weryfikacji T12).
SETTLE_SECONDS=10
out=reports/mutation-check

for tool in kubectl uv hubble; do
  if ! command -v "$tool" >/dev/null; then
    echo "Brak $tool w PATH: zainstaluj narzędzia z mise.toml (mise install)." >&2
    exit 1
  fi
done

k() { kubectl --context "$KUBE_CONTEXT" "$@"; }

# Testy sieci z logiem w pliku $1; kod wyjścia to kod pytest (0: zielone, 1: porażki, inny: błąd przebiegu).
run_tests() {
  local status=0
  uv run --locked pytest "$TESTS" -q -rfE --color=no 2>&1 | tee "$1" || status=$?
  return "$status"
}

# Posortowane identyfikatory testów z porażką (linie FAILED) z logu $1. Błąd (ERROR) nie jest porażką testu:
# oznacza, że fixture albo zbieranie nie dało rady, więc połączenia mogło nie sprawdzić nic.
failed_ids() {
  grep -E '^FAILED ' "$1" | cut -d ' ' -f 2 | LC_ALL=C sort -u || true
}

# Posortowane identyfikatory testów z błędem (linie ERROR) z logu $1; w przebiegu z mutacją każdy to wynik nieoczekiwany.
errored_ids() {
  grep -E '^ERROR ' "$1" | cut -d ' ' -f 2 | LC_ALL=C sort -u || true
}

mutated=false
# Błąd kubectl kończy funkcję kodem 1 jawnie, bo w warunku `if ! restore` (on_exit) set -e nie działa.
restore() {
  [ "$mutated" = true ] || return 0
  echo "== Przywracam shop/default-deny: kubectl apply -f $POLICY"
  k apply -f "$POLICY" || return 1
  mutated=false
  sleep "$SETTLE_SECONDS"
}

on_exit() {
  local status=$?
  # Przywracania polityki nie może przerwać kolejny Ctrl+C ani SIGTERM.
  trap '' INT TERM
  if ! restore; then
    echo "Polityka shop/default-deny NIE wróciła. Przywróć ją: kubectl --context $KUBE_CONTEXT apply -f $POLICY" >&2
    status=1
  fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! k -n shop get networkpolicy default-deny >/dev/null; then
  echo "Brak polityki shop/default-deny albo klastra $KUBE_CONTEXT: najpierw make up (albo make deploy)." >&2
  exit 1
fi
mkdir -p "$out"
# Stary log z poprzedniego uruchomienia nie może udawać nowego.
rm -f "$out/mutated.txt" "$out/restored.txt"

echo "== Mutacja: usuwam shop/default-deny"
mutated=true
k -n shop delete networkpolicy default-deny
sleep "$SETTLE_SECONDS"

echo "== Testy bez shop/default-deny; muszą paść dokładnie:"
echo "$EXPECTED_FAILED"
status=0
run_tests "$out/mutated.txt" || status=$?
failed=$(failed_ids "$out/mutated.txt")
errored=$(errored_ids "$out/mutated.txt")
expected=$(echo "$EXPECTED_FAILED" | LC_ALL=C sort -u)
if [ "$status" -eq 0 ]; then
  echo "Mutacja przeżyła: bez shop/default-deny wszystkie testy przechodzą." >&2
  exit 1
fi
if [ "$status" -ne 1 ] || [ -n "$errored" ] || [ "$failed" != "$expected" ]; then
  echo "Nieoczekiwany wynik bez shop/default-deny (kod pytest $status). Linie FAILED i ERROR:" >&2
  echo "FAILED: ${failed:-(brak)}" >&2
  echo "ERROR: ${errored:-(brak)}" >&2
  exit 1
fi

restore

echo "== Testy po przywróceniu shop/default-deny; muszą przejść"
status=0
run_tests "$out/restored.txt" || status=$?
if [ "$status" -ne 0 ]; then
  echo "Po przywróceniu shop/default-deny testy nie przechodzą (kod pytest $status)." >&2
  exit 1
fi
echo "Mutacja wykryta: bez shop/default-deny padają dokładnie oczekiwane testy, z polityką wszystkie przechodzą."
echo "Logi: $out/mutated.txt, $out/restored.txt."
