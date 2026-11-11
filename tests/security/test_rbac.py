# RBAC (T11) na działającym klastrze: konta usług bez tokenu API i role zespołu
# (docs/architektura.md, sekcja „RBAC”; manifesty w deploy/base/rbac).
# Uprawnienia sprawdza `kubectl auth can-i` z impersonacją (--as, --as-group),
# więc kontekst kubectl musi móc impersonować (admin klastra kind z `make up`).
# Uruchomienie: uv run --locked pytest tests/security/test_rbac.py
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
SA_TOKEN_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"

# Konta z deploy/base/rbac/serviceaccounts.yaml: (namespace, nazwa workloadu).
SERVICE_ACCOUNTS = [
    ("shop", "frontend"),
    ("shop", "orders"),
    ("loadgen", "locust"),
    ("loadgen", "fault-runner"),
    ("aiops", "anomaly-detector"),
    ("intruder", "intruder"),
    ("monitoring", "mailpit"),
]
# Wdrożone workloady; anomaly-detector dochodzi w T24.
DEPLOYED_WORKLOADS = {
    ("shop", "frontend"),
    ("shop", "orders"),
    ("loadgen", "locust"),
    ("loadgen", "fault-runner"),
    ("intruder", "intruder"),
    ("monitoring", "mailpit"),
}

TEAM_IDENTITIES = {
    "developer": ("--as=t11-developer", "--as-group=team:developers"),
    "sre": ("--as=t11-sre", "--as-group=team:sre"),
    "bez-zespolu": ("--as=t11-bez-zespolu",),
}
DEVELOPER_NAMESPACES = ("shop", "loadgen", "aiops")
DEVELOPER_READS = [
    ("list", "pods"),
    ("get", "pods/log"),
    ("watch", "deployments.apps"),
    ("list", "services"),
    ("list", "configmaps"),
    ("list", "events"),
]
DEVELOPER_DENIED = [
    ("get", "secrets"),
    ("list", "secrets"),
    ("create", "pods/exec"),
    ("delete", "pods"),
    ("patch", "deployments.apps"),
    ("create", "configmaps"),
]

# (kto, czasownik, zasób[/podzasób], namespace albo None = cały klaster, odpowiedź)
MATRIX = [
    # team:developers: odczyt w shop, loadgen i aiops
    *[
        ("developer", verb, resource, namespace, True)
        for namespace in DEVELOPER_NAMESPACES
        for verb, resource in DEVELOPER_READS
    ],
    # team:developers: bez sekretów, exec i zapisu
    *[
        ("developer", verb, resource, namespace, False)
        for namespace in DEVELOPER_NAMESPACES
        for verb, resource in DEVELOPER_DENIED
    ],
    # team:developers: nic poza shop, loadgen i aiops
    ("developer", "list", "pods", "kube-system", False),
    ("developer", "list", "pods", "monitoring", False),
    ("developer", "list", "pods", "intruder", False),
    # team:sre: odczyt w całym klastrze
    ("sre", "list", "pods", None, True),
    ("sre", "get", "pods/log", "kube-system", True),
    ("sre", "get", "nodes", None, True),
    ("sre", "list", "clusterroles.rbac.authorization.k8s.io", None, True),
    ("sre", "watch", "deployments.apps", None, True),
    # team:sre: bez sekretów, zapisu, exec i proxy kubeletu
    ("sre", "get", "secrets", "shop", False),
    ("sre", "list", "secrets", None, False),
    ("sre", "delete", "pods", "shop", False),
    ("sre", "update", "deployments.apps", "shop", False),
    ("sre", "create", "pods/exec", "shop", False),
    ("sre", "get", "nodes/proxy", None, False),
    # konta usług: żadnych uprawnień, także we własnym namespace
    *[
        (f"sa:{namespace}/{name}", verb, resource, namespace, False)
        for namespace, name in SERVICE_ACCOUNTS
        for verb, resource in (("list", "secrets"), ("get", "pods"))
    ],
    # kontrola: użytkownik bez grupy zespołu
    ("bez-zespolu", "list", "pods", "shop", False),
]


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["kubectl", "--context", KUBE_CONTEXT, *args],
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


def identity(who: str) -> tuple[str, ...]:
    if who.startswith("sa:"):
        namespace, name = who.removeprefix("sa:").split("/")
        # Impersonacja konta dodaje grupy system:serviceaccounts(:<namespace>).
        return (f"--as=system:serviceaccount:{namespace}:{name}",)
    return TEAM_IDENTITIES[who]


def can_i(who: str, verb: str, resource: str, namespace: str | None) -> bool:
    # `can-i get pods/log` znaczy pod o nazwie log, więc podzasób idzie osobno.
    name, _, subresource = resource.partition("/")
    args = ["auth", "can-i", verb, name]
    if subresource:
        args.append(f"--subresource={subresource}")
    args += ["-n", namespace] if namespace else ["-A"]
    result = kubectl(*args, *identity(who), check=False)
    # Nieznany zasób to `no` na stdout i ostrzeżenie tylko na stderr, więc
    # wiersz „deny” z literówką przeszedłby bez sprawdzania czegokolwiek.
    if "doesn't have a resource type" in result.stderr:
        pytest.fail(f"kubectl {' '.join(args)}: {result.stderr.strip()}")
    answer = result.stdout.strip()
    if answer.startswith("yes"):
        return True
    if answer.startswith("no"):
        return False
    pytest.fail(f"kubectl {' '.join(args)} ({who}): {result.stderr}")


@pytest.fixture(scope="module", autouse=True)
def cluster() -> None:
    if shutil.which("kubectl") is None:
        pytest.fail("Brak kubectl w PATH: aktywuj mise albo użyj `mise exec --`.")
    result = kubectl("get", "--raw", "/readyz", check=False)
    if result.returncode != 0:
        pytest.fail(f"Klaster {KUBE_CONTEXT} niedostępny (make up): {result.stderr}")


@pytest.mark.parametrize(
    ("who", "verb", "resource", "namespace", "expected"),
    MATRIX,
    ids=[f"{w}-{v}-{r}-{n or 'klaster'}" for w, v, r, n, _ in MATRIX],
)
def test_permission_matrix(who, verb, resource, namespace, expected):
    assert can_i(who, verb, resource, namespace) is expected


def test_sre_reads_every_listable_resource_except_secrets():
    resources = kubectl("api-resources", "--verbs=list", "-o", "name").stdout.split()
    assert {"pods", "secrets", "deployments.apps"} <= set(resources)
    missing = [
        f"{verb} {r}"
        for r in resources
        if r != "secrets"
        for verb in ("get", "list", "watch")
        if not can_i("sre", verb, r, None)
    ]
    assert not missing, f"dopisz do deploy/base/rbac/sre-readonly.yaml: {missing}"


def test_team_roles_are_read_only():
    # Wykluczenia dowodzimy z reguł ról, nie z próbek `can-i`: żaden dopisany
    # podzasób (attach, portforward, proxy, token) ani czasownik nie przejdzie.
    roles = [get_json("clusterrole", "sre-readonly")] + [
        get_json("role", "developer", "-n", ns) for ns in DEVELOPER_NAMESPACES
    ]
    for role in roles:
        name = role["metadata"]["name"]
        assert "aggregationRule" not in role, name
        for rule in role["rules"]:
            resources = rule.get("resources", [])
            assert set(rule["verbs"]) == {"get", "list", "watch"}, (name, rule)
            assert "*" not in rule["apiGroups"] + resources, (name, rule)
            assert "secrets" not in resources, (name, rule)
            assert {r for r in resources if "/" in r} <= {"pods/log"}, (name, rule)
            assert not rule.get("nonResourceURLs"), (name, rule)
            assert not rule.get("resourceNames"), (name, rule)


@pytest.mark.parametrize(("namespace", "name"), SERVICE_ACCOUNTS)
def test_service_account_does_not_automount_token(namespace, name):
    account = get_json("serviceaccount", name, "-n", namespace)
    assert account.get("automountServiceAccountToken") is False


def test_service_accounts_have_no_rbac_bindings():
    accounts = set(SERVICE_ACCOUNTS)
    namespace_groups = {f"system:serviceaccounts:{ns}" for ns, _ in SERVICE_ACCOUNTS}
    sa_users = {f"system:serviceaccount:{ns}:{name}" for ns, name in SERVICE_ACCOUNTS}
    found = []
    for binding in get_json("rolebindings,clusterrolebindings", "-A")["items"]:
        meta = binding["metadata"]
        for subject in binding.get("subjects") or []:
            account = (subject.get("namespace", meta.get("namespace")), subject["name"])
            if (
                (subject["kind"] == "ServiceAccount" and account in accounts)
                or (subject["kind"] == "User" and subject["name"] in sa_users)
                or (subject["kind"] == "Group" and subject["name"] in namespace_groups)
            ):
                where = f"{meta.get('namespace', '')}/{meta['name']}"
                found.append(f"{binding['kind']} {where}")
    assert not found


def test_own_deployments_use_their_service_account():
    accounts = {}
    for deployment in get_json("deployments", "-A", "-l", PART_OF)["items"]:
        key = (deployment["metadata"]["namespace"], deployment["metadata"]["name"])
        accounts[key] = deployment["spec"]["template"]["spec"].get("serviceAccountName")
    assert DEPLOYED_WORKLOADS <= accounts.keys()
    # Każdy własny Deployment działa na koncie o swojej nazwie z SERVICE_ACCOUNTS.
    wrong = {
        key: account
        for key, account in accounts.items()
        if key not in SERVICE_ACCOUNTS or account != key[1]
    }
    assert not wrong


def test_own_pods_have_no_service_account_token():
    running = get_json(
        "pods", "-A", "-l", PART_OF, "--field-selector=status.phase=Running"
    )
    pods = [p for p in running["items"] if "deletionTimestamp" not in p["metadata"]]
    workloads = {
        (p["metadata"]["namespace"], p["metadata"]["labels"]["app.kubernetes.io/name"])
        for p in pods
    }
    assert DEPLOYED_WORKLOADS <= workloads
    exposed = []
    for pod in pods:
        namespace, name = pod["metadata"]["namespace"], pod["metadata"]["name"]
        for container in pod["spec"]["containers"]:
            target = ["exec", name, "-n", namespace, "-c", container["name"]]
            result = kubectl(*target, "--", "ls", SA_TOKEN_DIR, check=False)
            # Sukces to tylko brak ścieżki; brak `ls` w obrazie też oblewa test.
            if "No such file or directory" not in result.stderr:
                output = (result.stdout or result.stderr).strip()
                exposed.append(f"{namespace}/{name}/{container['name']}: {output}")
    assert not exposed
