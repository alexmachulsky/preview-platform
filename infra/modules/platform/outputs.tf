###############################################################################
# Hostnames
###############################################################################

output "argocd_hostname" {
  description = "Ingress hostname for the Argo CD UI/API."
  value       = local.argocd_host
}

output "grafana_hostname" {
  description = "Ingress hostname for Grafana."
  value       = local.grafana_host
}

output "prometheus_hostname" {
  description = "Ingress hostname for the Prometheus UI."
  value       = local.prometheus_host
}

output "ingress_class_name" {
  description = "IngressClass previews should target (it is also the cluster default)."
  value       = var.ingress_class_name
}

###############################################################################
# Namespaces
###############################################################################

output "argocd_namespace" {
  description = "Namespace Argo CD runs in."
  value       = kubernetes_namespace_v1.argocd.metadata[0].name
}

output "monitoring_namespace" {
  description = "Namespace the observability stack runs in."
  value       = kubernetes_namespace_v1.monitoring.metadata[0].name
}

output "ingress_namespace" {
  description = "Namespace the ingress controller runs in."
  value       = kubernetes_namespace_v1.ingress.metadata[0].name
}

###############################################################################
# GitOps handoff
#
# The ApplicationSet is deliberately not created by this module — platform/argocd/
# owns it. These outputs are the contract it binds to.
###############################################################################

output "preview_project_name" {
  description = "Argo CD AppProject that preview Applications must belong to."
  value       = var.preview_project_name

  # The AppProject ships inside the Argo CD release; consuming this output
  # before that release exists would let an ApplicationSet reference a project
  # that is not there yet.
  depends_on = [helm_release.argocd]
}

output "preview_project_namespace" {
  description = "Namespace the preview AppProject (and the Applications) live in."
  value       = kubernetes_namespace_v1.argocd.metadata[0].name

  depends_on = [helm_release.argocd]
}

output "preview_namespace_pattern" {
  description = "Namespace glob the preview AppProject permits."
  value       = var.preview_namespace_pattern
}

output "git_repo_url" {
  description = "Repository Argo CD is configured to deploy from."
  value       = trimsuffix(var.git_repo_url, ".git")
}

output "argocd_repository_secret_name" {
  description = "Name of the Argo CD repository credentials Secret, or null when the repo is public."
  value       = one(kubernetes_secret_v1.argocd_repository[*].metadata[0].name)
}

###############################################################################
# Versions actually installed
###############################################################################

output "chart_versions" {
  description = "Pinned chart versions installed by this module."
  value = merge(
    {
      ingress_nginx         = var.ingress_nginx_chart_version
      argo_cd               = var.argocd_chart_version
      kube_prometheus_stack = var.kube_prometheus_stack_chart_version
    },
    var.enable_loki ? { loki_stack = var.loki_chart_version } : {}
  )
}
