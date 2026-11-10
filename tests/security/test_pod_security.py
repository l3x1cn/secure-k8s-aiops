# Pod Security (T13) na działającym klastrze: PSA restricted odrzuca uprzywilejowany
# pod, a kontenery własnych workloadów mają securityContext z kontraktu
# (docs/architektura.md, sekcja „Namespace'y i Pod Security”; etykiety PSA
# w deploy/base/namespaces.yaml). Pod próbny idzie przez `kubectl apply
# --dry-run=server`: przechodzi admission, ale nic nie powstaje w klastrze.
# Etykiet warn i audit test nie sprawdza, bo w kind nie mają obserwowalnego skutku:
# bez etykiety warn PSA bierze poziom z enforce, a audit działa tylko z logiem
# audytu, którego kind nie ma. Pokazuje je `kubectl get ns -L
# pod-security.kubernetes.io/warn,pod-security.kubernetes.io/audit`.
# Uruchomienie: uv run --locked pytest tests/security/test_pod_security.py
# (kubectl z mise.toml w PATH). Kontekst: zmienna KUBE_CONTEXT, domyślnie
# kind-secure-k8s-aiops, jak w Makefile.
import json
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.security

KUBE_CONTEXT = os.environ.get("KUBE_CONTEXT", "kind-secure-k8s-aiops")
PART_OF = "app.kubernetes.io/part-of=secure-k8s-aiops"
# Namespace'y z PSA restricted (tabela w architekturze); monitoring ma privileged.
RESTRICTED_NAMESPACES = ["shop", "loadgen", "aiops", "intruder"]
# Obrazy budowane w projekcie (IMAGE_REPO w Makefile, USER 10001:10001).
OWN_IMAGE_REPO = "ghcr.io/l3x1cn/secure-k8s-aiops/"
OWN_UID = 10001
# Dry-run nie pobiera obrazu, więc tag :dev wystarcza także poza kind.
PROBE_IMAGE = f"{OWN_IMAGE_REPO}orders:dev"


def kubectl(
    *args: str, stdin: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        pytest.fail(f"kubectl {command}: kod {result.returncode}, {result.stderr}")
    return result


def get_json(*args: str) -> dict:
    return json.loads(kubectl("get", *args, "-o", "json").stdout)


def privileged_pod(namespace: str) -> str:
    # privileged: true daje kontenerowi wszystkie capabilities i urządzenia hosta.
    return json.dumps(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "t13-privileged", "namespace": namespace},
            "spec": {
                "containers": [
                    {
                        "name": "probe",
                        "image": PROBE_IMAGE,
                        "securityContext": {"privileged": True},
                    }
                ]
            },
        }
    )


def hardening_problems(pod: dict, container: dict) -> list[str]:
    """Odstępstwa kontenera od kontraktu T13; pusta lista oznacza zgodność."""
    pod_context = pod["spec"].get("securityContext", {})
    context = container.get("securityContext", {})
    # Pola obecne w obu miejscach: wartość kontenera ma pierwszeństwo.
    run_as_non_root = context.get("runAsNonRoot", pod_context.get("runAsNonRoot"))
    run_as_user = context.get("runAsUser", pod_context.get("runAsUser"))
    seccomp = context.get("seccompProfile", pod_context.get("seccompProfile", {}))
    capabilities = context.get("capabilities", {})
    volumes = {volume["name"]: volume for volume in pod["spec"].get("volumes", [])}
    tmp = [
        mount["name"]
        for mount in container.get("volumeMounts", [])
        if mount["mountPath"] == "/tmp"
    ]

    problems = []
    if run_as_non_root is not True:
        problems.append("runAsNonRoot != true")
    # Obraz zewnętrzny może mieć inny UID; runAsNonRoot i tak wyklucza roota.
    if container["image"].startswith(OWN_IMAGE_REPO) and run_as_user != OWN_UID:
        problems.append(f"runAsUser {run_as_user} != {OWN_UID}")
    if context.get("readOnlyRootFilesystem") is not True:
        problems.append("readOnlyRootFilesystem != true")
    if context.get("allowPrivilegeEscalation") is not False:
        problems.append("allowPrivilegeEscalation != false")
    if capabilities.get("drop") != ["ALL"] or capabilities.get("add"):
        problems.append(f"capabilities {capabilities} zamiast drop: [ALL] bez add")
    if seccomp.get("type") != "RuntimeDefault":
        problems.append(f"seccompProfile {seccomp} zamiast RuntimeDefault")
    if not tmp or "emptyDir" not in volumes[tmp[0]]:
        problems.append("/tmp bez wolumenu emptyDir")
    return problems


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    result = kubectl("get", "--raw", "/readyz", check=False)
    if result.returncode != 0:
        pytest.fail(f"Klaster {KUBE_CONTEXT} niedostępny (make up): {result.stderr}")


@pytest.mark.parametrize("namespace", RESTRICTED_NAMESPACES)
def test_privileged_pod_is_rejected(namespace):
    result = kubectl(
        "apply",
        "--dry-run=server",
        "-f",
        "-",
        stdin=privileged_pod(namespace),
        check=False,
    )
    assert result.returncode != 0, f"pod przyjęty: {result.stdout}"
    # Komunikat podaje poziom enforce, więc baseline w etykiecie też oblewa test.
    assert 'violates PodSecurity "restricted:' in result.stderr, result.stderr
    assert "must not set securityContext.privileged=true" in result.stderr


def test_own_containers_are_hardened():
    listed = get_json("pods", "-A", "-l", PART_OF)
    pods = [p for p in listed["items"] if "deletionTimestamp" not in p["metadata"]]
    assert pods, f"brak podów z etykietą {PART_OF} (make deploy)"
    images = [c["image"] for p in pods for c in p["spec"]["containers"]]
    # Bez obrazu projektu sprawdzenie UID nic nie obejmuje (np. po zmianie IMAGE_REPO).
    assert any(image.startswith(OWN_IMAGE_REPO) for image in images), images
    problems = []
    for pod in pods:
        namespace, name = pod["metadata"]["namespace"], pod["metadata"]["name"]
        spec = pod["spec"]
        for container in spec.get("initContainers", []) + spec["containers"]:
            for problem in hardening_problems(pod, container):
                problems.append(f"{namespace}/{name}/{container['name']}: {problem}")
    assert not problems, "\n".join(problems)
