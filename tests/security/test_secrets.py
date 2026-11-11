# Sekrety poza repozytorium (T14): w deploy/ nie ma Secretu z data ani stringData,
# a gitleaks nie znajduje sekretów w historii HEAD. Sekrety tworzy przy wdrożeniu
# `make secrets` (scripts/secrets.sh; docs/architektura.md, sekcja „Sekrety”).
# Test nie potrzebuje klastra. Sprawdza każdy plik YAML w deploy/ (także taki,
# którego nie dołącza żaden kustomization) i wynik `kustomize build` każdego
# overlayu z deploy/overlays (Secret z secretGenerator). Historię skanuje
# `make gitleaks`, jak wymagany job CI `secrets`: tylko HEAD, bo inne gałęzie
# (np. origin/t06-test-sekret) celowo mają fałszywy klucz.
# Uruchomienie: uv run --locked pytest tests/security/test_secrets.py
# (kustomize z mise.toml w PATH; make sam dodaje narzędzia z mise do PATH).
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.security

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"


def secrets_with_values(document: object) -> list[str]:
    """Secrety z niepustym data albo stringData; w kind: List także elementy."""
    if not isinstance(document, dict):
        return []
    if document.get("kind") == "List":
        items = document.get("items") or []
        return [found for item in items for found in secrets_with_values(item)]
    if document.get("kind") != "Secret":
        return []
    if not (document.get("data") or document.get("stringData")):
        return []
    metadata = document.get("metadata") or {}
    return [f"Secret {metadata.get('namespace', '-')}/{metadata.get('name', '-')}"]


def test_deploy_files_have_no_secret_values():
    paths = sorted(
        path
        for path in DEPLOY.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )
    assert paths, f"brak plików YAML w {DEPLOY}"
    found = []
    for path in paths:
        with path.open() as stream:
            for document in yaml.safe_load_all(stream):
                for secret in secrets_with_values(document):
                    found.append(f"{path.relative_to(REPO_ROOT)}: {secret}")
    assert not found, "\n".join(found)


def test_overlays_render_no_secret_values():
    if shutil.which("kustomize") is None:
        pytest.fail("Brak kustomize w PATH: aktywuj mise albo użyj `mise exec --`.")
    overlays = sorted(
        path.parent for path in DEPLOY.glob("overlays/*/kustomization.yaml")
    )
    assert overlays, "brak overlayów z kustomization.yaml w deploy/overlays"
    found = []
    for overlay in overlays:
        name = overlay.relative_to(REPO_ROOT)
        result = subprocess.run(
            ["kustomize", "build", str(overlay)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"kustomize build {name}: {result.stderr}"
        for document in yaml.safe_load_all(result.stdout):
            for secret in secrets_with_values(document):
                found.append(f"{name}: {secret}")
    assert not found, "\n".join(found)


def test_history_has_no_leaks():
    # make gitleaks ma --redact, więc komunikat błędu nie pokazuje wartości.
    result = subprocess.run(
        ["make", "gitleaks"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
