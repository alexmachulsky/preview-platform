###############################################################################
# Naming and networking
###############################################################################

variable "base_domain" {
  description = <<-EOT
    Wildcard base domain the platform is served from. Every platform hostname is
    a subdomain of it (argocd.<base_domain>, grafana.<base_domain>, ...) and
    preview environments will use pr-<N>.<base_domain>.
  EOT
  type        = string

  validation {
    condition     = length(trimspace(var.base_domain)) > 0
    error_message = "base_domain must not be empty."
  }
}

variable "external_http_port" {
  description = <<-EOT
    Port the ingress controller is reachable on *from outside the cluster*.
    On k3d this is the host port mapped to the load balancer's :80. It is not
    used for routing (the ingress always listens on 80 inside the cluster) but
    it must be baked into Grafana's root_url so that redirects keep the port.
  EOT
  type        = number
  default     = 80
}

variable "ingress_class_name" {
  description = "Name of the IngressClass created by ingress-nginx, and the default class for the cluster."
  type        = string
  default     = "nginx"
}

variable "nginx_worker_processes" {
  description = <<-EOT
    nginx worker processes per controller pod. Must be a small fixed number, not
    "auto": nginx reads the *host* CPU count, not the container's CPU limit, so
    on a many-core workstation "auto" spawns one worker per core and the
    controller is OOMKilled inside its memory limit before it ever serves a
    request.
  EOT
  type        = number
  default     = 2
}

###############################################################################
# Namespaces
###############################################################################

variable "ingress_namespace" {
  description = "Namespace for the ingress controller."
  type        = string
  default     = "ingress-nginx"
}

variable "argocd_namespace" {
  description = "Namespace for Argo CD."
  type        = string
  default     = "argocd"
}

variable "monitoring_namespace" {
  description = "Namespace for Prometheus, Grafana, Alertmanager and Loki."
  type        = string
  default     = "monitoring"
}

###############################################################################
# Chart versions — pinned, never floating
###############################################################################

variable "ingress_nginx_chart_version" {
  description = "ingress-nginx/ingress-nginx chart version."
  type        = string
  default     = "4.15.1"
}

variable "argocd_chart_version" {
  description = "argo/argo-cd chart version."
  type        = string
  default     = "10.3.2"
}

variable "kube_prometheus_stack_chart_version" {
  description = "prometheus-community/kube-prometheus-stack chart version."
  type        = string
  default     = "88.2.0"
}

variable "loki_chart_version" {
  description = "grafana/loki-stack chart version."
  type        = string
  default     = "2.10.2"
}

###############################################################################
# Helm behaviour
###############################################################################

variable "helm_timeout_seconds" {
  description = "Per-release Helm timeout. kube-prometheus-stack pulls a lot of images on a cold cluster."
  type        = number
  default     = 900
}

variable "helm_max_history" {
  description = "Number of Helm release revisions to keep (each one is a Secret in etcd)."
  type        = number
  default     = 5
}

###############################################################################
# Observability tuning
###############################################################################

variable "prometheus_retention" {
  description = "Prometheus time-based retention. Kept short: this stack shares a laptop with the previews it watches."
  type        = string
  default     = "6h"
}

variable "prometheus_retention_size" {
  description = "Prometheus size-based retention. Storage is an emptyDir, so this is the real guard rail."
  type        = string
  default     = "2GB"
}

variable "grafana_admin_user" {
  description = "Grafana admin username."
  type        = string
  default     = "admin"
}

variable "grafana_admin_password" {
  description = "Grafana admin password. Anonymous users get Viewer access without it."
  type        = string
  default     = "admin"
  sensitive   = true
}

variable "grafana_anonymous_access" {
  description = "Allow unauthenticated read-only access to Grafana. Convenient locally, must be false on a public cluster."
  type        = bool
  default     = true
}

variable "enable_loki" {
  description = "Install Loki + promtail and wire Loki up as a Grafana datasource."
  type        = bool
  default     = true
}

variable "loki_retention_hours" {
  description = "How long Loki keeps log chunks, in hours."
  type        = number
  default     = 24
}

###############################################################################
# Argo CD / GitOps
###############################################################################

variable "git_repo_url" {
  description = "HTTPS URL of the Git repository Argo CD watches for preview environments."
  type        = string
  default     = "https://github.com/alexmachulsky/preview-platform"
}

variable "github_token" {
  description = <<-EOT
    GitHub token used by Argo CD to read the repository and (later) the
    pullRequest generator. Leave empty for a public repository: no repository
    Secret is created at all and Argo CD uses the anonymous path.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_username" {
  description = "Username paired with github_token in the Argo CD repository Secret. Ignored when github_token is empty."
  type        = string
  default     = "git"
}

variable "preview_project_name" {
  description = "Name of the Argo CD AppProject that owns every preview Application."
  type        = string
  default     = "previews"
}

variable "preview_namespace_pattern" {
  description = "Glob the preview AppProject is allowed to deploy into. Must match what the ApplicationSet generates."
  type        = string
  default     = "preview-*"
}

variable "argocd_insecure" {
  description = "Run argocd-server without its own TLS. Correct when TLS terminates at the ingress; leave true for the local stack."
  type        = bool
  default     = true
}
