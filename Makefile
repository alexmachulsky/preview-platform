# ──────────────────────────────────────────────────────────────────────────────
# Preview Platform — ephemeral PR environments on Kubernetes
# ──────────────────────────────────────────────────────────────────────────────
SHELL := /bin/bash
.DEFAULT_GOAL := help

CLUSTER     ?= preview-platform
AGENTS      ?= 2

# Host ports for the k3d load balancer. Apache owns :80 on this machine, so the
# platform lands on 8080/8443 by default. Use HTTP_PORT=80 HTTPS_PORT=443 if free.
HTTP_PORT   ?= 8080
HTTPS_PORT  ?= 8443

# Wildcard DNS for preview hostnames, with zero local configuration.
# *.localtest.me resolves to 127.0.0.1 (and ::1) for any label.
#
# NOTE: sslip.io and nip.io — the usual choices — are unusable on this network.
# The resolver at 192.168.13.192 hijacks both to 208.91.112.55. Verify before
# switching: `getent ahostsv4 pr-1.$(BASE_DOMAIN)` must return 127.0.0.1.
BASE_DOMAIN ?= localtest.me

CONTEXT     := k3d-$(CLUSTER)
TF_DIR      := infra/local

# Debian and Ubuntu ship no `python` unless python-is-python3 is installed, so
# spelling it out is the difference between `make test` working on a fresh
# checkout and failing with "command not found". A virtualenv that provides
# `python` still wins: override with PYTHON=python.
PYTHON      ?= python3

# ── Cluster lifecycle ─────────────────────────────────────────────────────────

.PHONY: up
up: ## Create the local k3d cluster (idempotent)
	@if k3d cluster list $(CLUSTER) >/dev/null 2>&1; then \
	  echo "→ cluster '$(CLUSTER)' already exists"; \
	else \
	  k3d cluster create $(CLUSTER) \
	    --agents $(AGENTS) \
	    --port "$(HTTP_PORT):80@loadbalancer" \
	    --port "$(HTTPS_PORT):443@loadbalancer" \
	    --k3s-arg "--disable=traefik@server:*" \
	    --wait; \
	fi
	@kubectl config use-context $(CONTEXT) >/dev/null
	@kubectl wait --for=condition=Ready nodes --all --timeout=180s
	@echo "✓ cluster ready — $$(kubectl get nodes --no-headers | wc -l) nodes"

.PHONY: down
down: ## Delete the local k3d cluster and everything in it
	k3d cluster delete $(CLUSTER)

.PHONY: bootstrap
bootstrap: ## Install the platform (ingress-nginx, Argo CD, monitoring) via Terraform
	cd $(TF_DIR) && terraform init -upgrade && terraform apply -auto-approve \
	  -var 'base_domain=$(BASE_DOMAIN)'

.PHONY: unbootstrap
unbootstrap: ## Remove the platform, keeping the cluster
	cd $(TF_DIR) && terraform destroy -auto-approve -var 'base_domain=$(BASE_DOMAIN)'

# ── Application development ───────────────────────────────────────────────────

.PHONY: dev
dev: ## Run api + worker + postgres locally with docker compose
	docker compose up --build

.PHONY: dev-down
dev-down: ## Stop the docker compose stack and drop its volumes
	docker compose down -v

.PHONY: test
test: ## Run unit tests for both services
	cd apps/api && $(PYTHON) -m pytest -q
	cd apps/worker && $(PYTHON) -m pytest -q

.PHONY: lint
lint: ## Lint and format-check both services
	ruff check apps/
	ruff format --check apps/

.PHONY: chart-lint
chart-lint: ## Render and lint the preview-app chart
	helm dependency update charts/preview-app
	helm lint charts/preview-app
	helm template preview charts/preview-app >/dev/null && echo "✓ chart renders"

# ── Inspection ────────────────────────────────────────────────────────────────

.PHONY: urls
urls: ## Print the platform URLs
	@echo "Argo CD    http://argocd.$(BASE_DOMAIN):$(HTTP_PORT)"
	@echo "Grafana    http://grafana.$(BASE_DOMAIN):$(HTTP_PORT)"
	@echo "Prometheus http://prometheus.$(BASE_DOMAIN):$(HTTP_PORT)"
	@echo "Preview    http://pr-<N>.$(BASE_DOMAIN):$(HTTP_PORT)"

.PHONY: previews
previews: ## List live preview environments
	@kubectl get ns -l app.kubernetes.io/part-of=preview-platform \
	  -o custom-columns=NAMESPACE:.metadata.name,AGE:.metadata.creationTimestamp 2>/dev/null \
	  || echo "no preview namespaces"
	@kubectl get applications -n argocd 2>/dev/null || true

.PHONY: argocd-password
argocd-password: ## Print the Argo CD admin password
	@kubectl -n argocd get secret argocd-initial-admin-secret \
	  -o jsonpath='{.data.password}' | base64 -d; echo

.PHONY: status
status: ## Show cluster and platform health at a glance
	@kubectl get nodes
	@echo
	@kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null \
	  | grep -v '^No resources' || echo "✓ all pods Running/Succeeded"

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
