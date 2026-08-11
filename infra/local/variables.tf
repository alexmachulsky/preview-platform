variable "base_domain" {
  description = <<-EOT
    Wildcard base domain for every platform and preview hostname.

    `localtest.me` is a public domain whose wildcard records all resolve to
    loopback (A 127.0.0.1, AAAA ::1) at any label depth, so
    `pr-42.localtest.me` works with no /etc/hosts entry and no DNS setup.

    Do NOT switch this to sslip.io or nip.io. On this network the upstream
    resolver (192.168.13.192) hijacks both domains and answers 208.91.112.55
    for everything under them, so `argocd.127.0.0.1.sslip.io` does not resolve
    to loopback and every ingress hostname is unreachable. Verified with:
        getent ahostsv4 argocd.localtest.me   -> 127.0.0.1
        getent ahostsv4 argocd.127.0.0.1.sslip.io -> 208.91.112.55
  EOT
  type        = string
  default     = "localtest.me"
}

variable "http_port" {
  description = <<-EOT
    Host port the k3d load balancer publishes for the cluster's :80. Apache
    owns :80 on the development machine, so `make up` maps 8080 -> :80 and
    8443 -> :443. Used for the URL outputs and for Grafana's root_url.
  EOT
  type        = number
  default     = 8080
}

variable "kube_context" {
  description = "kubectl context of the local cluster. k3d prefixes the cluster name with 'k3d-'."
  type        = string
  default     = "k3d-preview-platform"
}

variable "kubeconfig_path" {
  description = "Path to the kubeconfig holding kube_context."
  type        = string
  default     = "~/.kube/config"
}

###############################################################################
# GitOps
###############################################################################

variable "git_repo_url" {
  description = "Repository Argo CD watches for pull requests to preview."
  type        = string
  default     = "https://github.com/alexmachulsky/preview-platform"
}

variable "github_token" {
  description = <<-EOT
    GitHub token for Argo CD's repository credentials. Leave empty for a public
    repository — no Secret is created and Argo CD uses the anonymous path.
    Supply it via TF_VAR_github_token rather than a committed tfvars file.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}

variable "github_username" {
  description = "Username paired with github_token. Ignored when the token is empty."
  type        = string
  default     = "git"
}

###############################################################################
# Observability
###############################################################################

variable "grafana_admin_password" {
  description = "Grafana admin password. Anonymous visitors already get Viewer access."
  type        = string
  default     = "admin"
  sensitive   = true
}

variable "prometheus_retention" {
  description = "Prometheus retention window. Short by default: this host also runs the previews."
  type        = string
  default     = "6h"
}

variable "enable_loki" {
  description = "Install Loki + promtail and provision the Grafana datasource."
  type        = bool
  default     = true
}
