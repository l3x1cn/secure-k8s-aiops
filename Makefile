# Narzędzia w wersjach z mise.toml mają pierwszeństwo przed systemowymi,
# także gdy mise nie jest aktywowane w powłoce.
export PATH := $(shell mise bin-paths 2>/dev/null | tr '\n' ':')$(PATH)

# Wersje chartów i obrazów zewnętrznych (T03, T04).
include platform/versions.env

CLUSTER_NAME := secure-k8s-aiops
KUBE_CONTEXT := kind-$(CLUSTER_NAME)
CILIUM_CHART := oci://quay.io/cilium/charts/cilium
PROMETHEUS_OPERATOR_CRDS_CHART := oci://ghcr.io/prometheus-community/charts/prometheus-operator-crds

.PHONY: doctor cluster hubble-ui hubble-relay

# Sprawdza narzędzia z mise.toml, dostęp do Dockera bez sudo, pamięć Dockera i limity inotify.
doctor:
	@bash scripts/doctor.sh

# Klaster kind z Cilium i Hubble. Idempotentny: istniejącego klastra nie tworzy ponownie,
# a helm upgrade --install doprowadza CRD i Cilium do wersji i digestów z platform/versions.env.
# CRD prometheus-operator (ServiceMonitor) muszą istnieć przed instalacją Cilium.
# Po Cilium stosuje NetworkPolicy Hubble (platform/cilium/hubble-networkpolicy.yaml): do Relay tylko z Hubble UI.
cluster:
	@if kind get clusters | grep -qx '$(CLUSTER_NAME)'; then \
		echo "Klaster $(CLUSTER_NAME) już istnieje."; \
	else \
		kind create cluster --name '$(CLUSTER_NAME)' --config platform/kind/cluster.yaml; \
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

# Hubble UI w przeglądarce: port-forward na localhost:12000, Ctrl+C kończy.
hubble-ui:
	cilium hubble ui --context $(KUBE_CONTEXT)

# Hubble Relay dla CLI: port-forward na localhost:4245 (domyślny adres hubble), Ctrl+C kończy.
# W osobnym terminalu: hubble observe --last 20
hubble-relay:
	cilium hubble port-forward --context $(KUBE_CONTEXT)
