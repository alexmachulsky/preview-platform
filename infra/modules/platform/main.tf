###############################################################################
# Preview Platform — in-cluster platform components
#
# Install order is not cosmetic. See README.md for the full reasoning:
#
#   ingress-nginx  ──►  loki  ──►  kube-prometheus-stack  ──►  argo-cd
#        │                              │                         │
#        │   admission webhook must     │  owns the ServiceMonitor/│
#        │   exist before anything      │  PodMonitor CRDs and the │
#        │   creates an Ingress         │  monitors for the other  │
#        │                              │  releases                │
#        └──────────────────────────────┴──────────────────────────┘
###############################################################################

locals {
  # Grafana needs the externally visible port in its root_url, otherwise every
  # redirect it issues drops back to :80.
  external_url_suffix = var.external_http_port == 80 ? "" : ":${var.external_http_port}"

  argocd_host     = "argocd.${var.base_domain}"
  grafana_host    = "grafana.${var.base_domain}"
  prometheus_host = "prometheus.${var.base_domain}"

  # Owner and repository for the GitHub API, derived from git_repo_url so there
  # is exactly one place to change the repository.
  #
  # Do NOT reuse github_username here. That variable is the *HTTPS auth* user
  # for the Argo CD repository Secret, where the convention with a token is the
  # literal "git" — which as an API owner produced
  # `api.github.com/repos/git/preview-platform` and a permanent 404.
  repo_url_clean = trimsuffix(var.git_repo_url, ".git")
  repo_slug      = regex("github\\.com[:/]([^/]+)/([^/]+)/?$", local.repo_url_clean)
  github_owner   = local.repo_slug[0]
  github_repo    = local.repo_slug[1]

  # loki-stack names its read/write Service after the release name.
  loki_release_name = "loki"
  loki_url          = "http://${local.loki_release_name}.${var.monitoring_namespace}.svc.cluster.local:3100"

  common_labels = {
    "app.kubernetes.io/part-of"    = "preview-platform"
    "app.kubernetes.io/managed-by" = "terraform"
  }
}

###############################################################################
# Namespaces
#
# Created by Terraform rather than `create_namespace = true` on each release so
# that the labels are ours and deletion order is explicit.
###############################################################################

resource "kubernetes_namespace_v1" "ingress" {
  metadata {
    name   = var.ingress_namespace
    labels = local.common_labels
  }
}

resource "kubernetes_namespace_v1" "argocd" {
  metadata {
    name   = var.argocd_namespace
    labels = local.common_labels
  }
}

resource "kubernetes_namespace_v1" "monitoring" {
  metadata {
    name   = var.monitoring_namespace
    labels = local.common_labels
  }
}

###############################################################################
# 1. ingress-nginx
#
# First, because it installs a ValidatingWebhookConfiguration for Ingress
# objects. Once that webhook exists but its backend does not, every subsequent
# Ingress creation fails. Installing it first with wait = true means the
# webhook is always serving before Argo CD / Grafana / Prometheus create theirs.
###############################################################################

resource "helm_release" "ingress_nginx" {
  name       = "ingress-nginx"
  repository = "https://kubernetes.github.io/ingress-nginx"
  chart      = "ingress-nginx"
  version    = var.ingress_nginx_chart_version
  namespace  = kubernetes_namespace_v1.ingress.metadata[0].name

  create_namespace = false
  wait             = true
  # The admission webhook certificate is produced by a pre-install Job.
  wait_for_jobs   = true
  timeout         = var.helm_timeout_seconds
  cleanup_on_fail = true
  max_history     = var.helm_max_history

  values = [
    templatefile("${path.module}/values/ingress-nginx.yaml.tpl", {
      ingress_class_name     = var.ingress_class_name
      nginx_worker_processes = var.nginx_worker_processes
    })
  ]
}

###############################################################################
# 2. Loki + promtail
#
# Installed before kube-prometheus-stack so that the Loki Service already
# resolves when Grafana boots with the provisioned Loki datasource. It creates
# no ServiceMonitor of its own, so it has no CRD dependency.
###############################################################################

resource "helm_release" "loki" {
  count = var.enable_loki ? 1 : 0

  name       = local.loki_release_name
  repository = "https://grafana.github.io/helm-charts"
  chart      = "loki-stack"
  version    = var.loki_chart_version
  namespace  = kubernetes_namespace_v1.monitoring.metadata[0].name

  create_namespace = false
  wait             = true
  timeout          = var.helm_timeout_seconds
  cleanup_on_fail  = true
  max_history      = var.helm_max_history

  values = [
    templatefile("${path.module}/values/loki.yaml.tpl", {
      loki_retention_hours = var.loki_retention_hours
    })
  ]
}

###############################################################################
# 3. kube-prometheus-stack
#
# Owns the Prometheus Operator CRDs. Everything that creates a ServiceMonitor,
# PodMonitor or PrometheusRule must be ordered after this release.
###############################################################################

resource "helm_release" "kube_prometheus_stack" {
  name       = "kube-prometheus-stack"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  version    = var.kube_prometheus_stack_chart_version
  namespace  = kubernetes_namespace_v1.monitoring.metadata[0].name

  create_namespace = false
  wait             = true
  timeout          = var.helm_timeout_seconds
  cleanup_on_fail  = true
  max_history      = var.helm_max_history

  values = [
    templatefile("${path.module}/values/kube-prometheus-stack.yaml.tpl", {
      ingress_class_name        = var.ingress_class_name
      ingress_namespace         = var.ingress_namespace
      monitoring_namespace      = var.monitoring_namespace
      grafana_host              = local.grafana_host
      prometheus_host           = local.prometheus_host
      grafana_root_url          = "http://${local.grafana_host}${local.external_url_suffix}/"
      grafana_admin_user        = var.grafana_admin_user
      grafana_anonymous_enabled = var.grafana_anonymous_access
      prometheus_retention      = var.prometheus_retention
      prometheus_retention_size = var.prometheus_retention_size
      loki_enabled              = var.enable_loki
      loki_url                  = local.loki_url
      # jsonencode keeps a password containing YAML-significant characters
      # (":", "#", "@", leading digits...) a single valid scalar.
      grafana_admin_password = jsonencode(var.grafana_admin_password)
    })
  ]

  depends_on = [
    # Ingress objects for Grafana and Prometheus need the admission webhook up.
    helm_release.ingress_nginx,
    # The Loki datasource points at a Service this release creates.
    helm_release.loki,
  ]
}

###############################################################################
# 4. Argo CD
#
# Last: it creates an Ingress (needs ingress-nginx) and ServiceMonitors for all
# of its components (needs the Prometheus Operator CRDs). The preview AppProject
# rides along inside this release via `extraObjects` — Helm applies a chart's
# crds/ directory before its templates, so the AppProject CRD is guaranteed to
# exist. A `kubernetes_manifest` would instead require the CRD to be present at
# plan time, which is impossible on a first apply.
###############################################################################

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = var.argocd_chart_version
  namespace  = kubernetes_namespace_v1.argocd.metadata[0].name

  create_namespace = false
  wait             = true
  timeout          = var.helm_timeout_seconds
  cleanup_on_fail  = true
  max_history      = var.helm_max_history

  values = [
    templatefile("${path.module}/values/argocd.yaml.tpl", {
      argocd_host               = local.argocd_host
      argocd_namespace          = var.argocd_namespace
      argocd_insecure           = var.argocd_insecure
      ingress_class_name        = var.ingress_class_name
      git_repo_url              = trimsuffix(var.git_repo_url, ".git")
      preview_project_name      = var.preview_project_name
      preview_namespace_pattern = var.preview_namespace_pattern
    })
  ]

  depends_on = [
    helm_release.ingress_nginx,
    # ServiceMonitor CRDs.
    helm_release.kube_prometheus_stack,
  ]
}

###############################################################################
# Repository credentials for Argo CD
#
# Optional: a public repository needs none, and passing an empty github_token
# is the supported "public repo" path. Plain core/v1 Secret, so no CRD ordering
# concern — but Argo CD only reads it from its own namespace.
###############################################################################

resource "kubernetes_secret_v1" "argocd_repository" {
  count = var.github_token == "" ? 0 : 1

  metadata {
    name      = "preview-platform-repo"
    namespace = kubernetes_namespace_v1.argocd.metadata[0].name
    labels = merge(local.common_labels, {
      "argocd.argoproj.io/secret-type" = "repository"
    })
  }

  data = {
    type     = "git"
    url      = trimsuffix(var.git_repo_url, ".git")
    username = var.github_username
    password = var.github_token
  }

  type = "Opaque"
}

###############################################################################
# GitHub token for the pullRequest generator
#
# Separate from the repository Secret above: that one authenticates `git fetch`
# and is keyed `password`, this one is read by the ApplicationSet controller to
# call the GitHub REST API and must be keyed `token`.
#
# Optional. Without it the generator polls anonymously at 60 requests/hour,
# which a 30-second requeue burns through in half an hour.
###############################################################################

resource "kubernetes_secret_v1" "github_pr_token" {
  count = var.github_token == "" ? 0 : 1

  metadata {
    name      = "preview-platform-github-token"
    namespace = kubernetes_namespace_v1.argocd.metadata[0].name
    labels    = local.common_labels
  }

  data = {
    token = var.github_token
  }

  type = "Opaque"
}

###############################################################################
# Preview bootstrap — the AppProject and the ApplicationSet
#
# A separate release from argo-cd on purpose. Both objects are instances of
# CRDs that the argo-cd chart installs, and Helm validates every manifest in a
# release against the API server before installing any of it. Shipping them
# inside that release fails on a fresh cluster with:
#
#   no matches for kind "AppProject" in version "argoproj.io/v1alpha1"
#
# depends_on gives the ordering the CRDs need.
###############################################################################

resource "helm_release" "preview_bootstrap" {
  name      = "preview-bootstrap"
  chart     = var.bootstrap_chart_path
  namespace = kubernetes_namespace_v1.argocd.metadata[0].name

  create_namespace = false
  wait             = true
  timeout          = var.helm_timeout_seconds
  cleanup_on_fail  = true
  max_history      = var.helm_max_history

  values = [
    yamlencode({
      argocdNamespace = var.argocd_namespace
      project = {
        name             = var.preview_project_name
        namespacePattern = var.preview_namespace_pattern
      }
      repo = {
        url       = trimsuffix(var.git_repo_url, ".git")
        chartPath = var.preview_chart_path
      }
      github = {
        owner = local.github_owner
        name  = local.github_repo
        # Empty when no PAT was supplied, which renders an anonymous generator.
        tokenSecretName = var.github_token == "" ? "" : kubernetes_secret_v1.github_pr_token[0].metadata[0].name
        tokenSecretKey  = "token"
      }
      applicationSet = {
        requeueAfterSeconds = var.preview_requeue_seconds
        # Terraform interpolates ${}, the ApplicationSet controller expands
        # {{}}. They do not collide, so the pattern can be built here.
        ingressHost = "pr-{{number}}.${var.base_domain}"
      }
    })
  ]

  depends_on = [
    helm_release.argocd,
    kubernetes_secret_v1.github_pr_token,
  ]
}
