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

.PHONY: doctor lint unit gitleaks manifests up down cluster namespaces secrets images deploy status urls hubble-ui hubble-relay prometheus alertmanager

# Sprawdza narzędzia z mise.toml, dostęp do Dockera bez sudo, pamięć Dockera, Docker Buildx, openssl i limity inotify.
doctor:
	@bash scripts/doctor.sh

# Kontrole CI (T06): każdy cel to jeden job w .github/workflows/ci.yml; lokalnie te same polecenia i wersje z mise.toml.
# Lint i formatowanie Pythona (job lint): ruff, reguły w pyproject.toml; obejmuje też notebooki.
lint:
	ruff check
	ruff format --check

# Testy jednostkowe bez klastra (job unit): testpaths w pyproject.toml. --locked: błąd, gdy uv.lock nie pasuje do pyproject.toml.
unit:
	uv run --locked pytest

# Sekrety w całej historii HEAD (job secrets): gitleaks z domyślnymi regułami; --redact ukrywa wartości w logu.
# Tylko historia HEAD (w PR: main + commity PR), więc sekret na innej gałęzi nie blokuje cudzych PR.
gitleaks:
	gitleaks git --no-banner --redact --verbose --log-opts=HEAD .

# Manifesty (job manifests): kustomize build każdego overlayu z deploy/overlays → kubeconform -strict (scripts/manifests.sh).
manifests:
	@bash scripts/manifests.sh

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
