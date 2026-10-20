#!/usr/bin/env bash
# Sprawdza, czy maszyna jest gotowa do pracy z projektem (T02).
# Uruchamiaj przez `make doctor`: Makefile stawia narzędzia z mise.toml na początku PATH.
# Kod wyjścia 0 tylko wtedy, gdy żadne sprawdzenie nie zwróciło FAIL. Zgodny z bash 3.2 (macOS).
set -u

cd "$(dirname "$0")/.." || exit 1

# Docker z nominalnymi 8 GB raportuje ok. 7,6 GiB (resztę zajmuje jądro), więc próg to 7 GiB.
MIN_DOCKER_MEM_BYTES=7516192768
MIN_INOTIFY_WATCHES=524288
MIN_INOTIFY_INSTANCES=512

failures=0

ok() { printf '[ OK ] %s\n' "$1"; }
skip() { printf '[SKIP] %s\n' "$1"; }
fail() {
  printf '[FAIL] %s\n' "$1"
  if [ -n "${2:-}" ]; then
    printf '       Napraw: %s\n' "$2"
  fi
  failures=$((failures + 1))
}
physical_dir() { (cd "$1" 2>/dev/null && pwd -P); }

check_sysctl() { # nazwa minimum
  value=$(cat "/proc/sys/$(printf '%s' "$1" | tr . /)")
  if [ "$value" -ge "$2" ]; then
    ok "$1 = $value"
  else
    fail "$1 = $value, wymagane co najmniej $2" \
      "sudo sysctl -w $1=$2 && echo '$1 = $2' | sudo tee -a /etc/sysctl.d/99-kind.conf"
  fi
}

echo "== Narzędzia z mise.toml =="
if ! command -v mise >/dev/null 2>&1; then
  fail "brak mise" "zainstaluj mise: https://mise.jdx.dev/getting-started.html"
else
  ok "mise $(mise --version 2>/dev/null | cut -d ' ' -f 1)"
  # klucz z [tools] w mise.toml i jego plik wykonywalny; nowe narzędzie dopisz w obu miejscach
  while read -r tool bin; do
    if ! dir=$(mise where "$tool" 2>/dev/null </dev/null); then
      fail "$tool: brak wersji z mise.toml" "mise install"
      continue
    fi
    tool_dir=$(physical_dir "$dir")
    path=$(command -v "$bin" 2>/dev/null || true)
    bin_dir=""
    if [ -n "$path" ]; then
      bin_dir=$(physical_dir "$(dirname "$path")")
    fi
    case "$bin_dir/" in
      "$tool_dir"/*) ok "$tool ${dir##*/}" ;;
      *) fail "$tool: $bin z PATH (${path:-brak}) to nie wersja ${dir##*/} z mise.toml" "uruchamiaj przez make (make doctor)" ;;
    esac
  done <<'EOF'
python python3
uv uv
kind kind
kubectl kubectl
helm helm
kustomize kustomize
cilium-cli cilium
github:cilium/hubble hubble
trivy trivy
gitleaks gitleaks
kubeconform kubeconform
promtool promtool
opentofu tofu
EOF
fi

echo "== Docker =="
docker_ok=0
if [ "$(id -u)" -eq 0 ]; then
  fail "make doctor uruchomione jako root" "uruchom bez sudo, jako zwykły użytkownik"
elif ! command -v docker >/dev/null 2>&1; then
  fail "brak polecenia docker" "zainstaluj Dockera według sekcji „Wymagania” w README"
elif ! docker_out=$(docker info --format '{{.ServerVersion}} {{.MemTotal}}' 2>&1); then
  case "$docker_out" in
    *"permission denied"*)
      fail "brak dostępu do Dockera bez sudo" 'sudo usermod -aG docker "$USER", potem wyloguj się i zaloguj ponownie' ;;
    *)
      fail "Docker nie odpowiada: $(printf '%s\n' "$docker_out" | head -n 1)" \
        "uruchom Dockera (Linux: sudo systemctl start docker; macOS i Windows: Docker Desktop)" ;;
  esac
else
  docker_ok=1
  ok "Docker ${docker_out% *}, dostęp bez sudo"
fi
if [ "$docker_ok" -eq 1 ]; then
  mem=${docker_out#* }
  mem_gib=$(awk -v b="$mem" 'BEGIN { printf "%.1f", b / 1073741824 }')
  if [ "$mem" -ge "$MIN_DOCKER_MEM_BYTES" ]; then
    ok "pamięć dla Dockera: $mem_gib GiB"
  else
    fail "pamięć dla Dockera: $mem_gib GiB, wymagane co najmniej 8 GB" \
      "macOS: Docker Desktop → Settings → Resources; Windows: memory= w %UserProfile%\\.wslconfig; Linux: maszyna z co najmniej 8 GB RAM"
  fi
else
  skip "pamięć dla Dockera (brak dostępu do Dockera)"
fi

echo "== Limity inotify (kind) =="
if [ -r /proc/sys/fs/inotify/max_user_watches ]; then
  check_sysctl fs.inotify.max_user_watches "$MIN_INOTIFY_WATCHES"
  check_sysctl fs.inotify.max_user_instances "$MIN_INOTIFY_INSTANCES"
else
  skip "limity inotify (sprawdzane tylko na Linuksie i w WSL2)"
fi

echo
if [ "$failures" -eq 0 ]; then
  echo "Wszystkie sprawdzenia przeszły."
else
  echo "Nieudane sprawdzenia: $failures. Napraw je i uruchom ponownie: make doctor"
  exit 1
fi
