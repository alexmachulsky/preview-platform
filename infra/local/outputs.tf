locals {
  # `make up` maps host 8080 -> cluster :80. Only append the port when it is not
  # the default, so switching to HTTP_PORT=80 produces clean URLs.
  url_suffix = var.http_port == 80 ? "" : ":${var.http_port}"
}

output "argocd_url" {
  description = "Argo CD UI."
  value       = "http://${module.platform.argocd_hostname}${local.url_suffix}"
}

output "grafana_url" {
  description = "Grafana. Anonymous visitors land as Viewer; log in as admin to edit."
  value       = "http://${module.platform.grafana_hostname}${local.url_suffix}"
}

output "prometheus_url" {
  description = "Prometheus UI — useful for checking that preview ServiceMonitors were picked up."
  value       = "http://${module.platform.prometheus_hostname}${local.url_suffix}"
}

output "preview_url_pattern" {
  description = "Where a preview environment for pull request N appears."
  value       = "http://pr-<N>.${var.base_domain}${local.url_suffix}"
}

output "argocd_admin_password_command" {
  description = "Argo CD generates a random initial admin password; this reads it back out."
  value       = "kubectl --context ${var.kube_context} -n ${module.platform.argocd_namespace} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo"
}

output "grafana_admin_user" {
  description = "Grafana admin username. The password is the grafana_admin_password variable."
  value       = "admin"
}

output "preview_project" {
  description = "Argo CD AppProject the ApplicationSet in platform/argocd/ must reference."
  value = {
    name      = module.platform.preview_project_name
    namespace = module.platform.preview_project_namespace
    # Applications may only deploy into namespaces matching this glob.
    namespace_pattern = module.platform.preview_namespace_pattern
    repo_url          = module.platform.git_repo_url
  }
}

output "ingress_class_name" {
  description = "IngressClass preview Ingress objects should use (also the cluster default)."
  value       = module.platform.ingress_class_name
}

output "chart_versions" {
  description = "Pinned chart versions installed into the cluster."
  value       = module.platform.chart_versions
}
