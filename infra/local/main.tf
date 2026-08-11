###############################################################################
# Preview Platform — local (k3d) root module
#
#   make up        creates the cluster
#   make bootstrap runs this
#   make urls      prints what the outputs below produce
#
# The cluster itself is not managed here on purpose: k3d owns its own lifecycle
# and Terraform only ever installs *into* an existing context.
###############################################################################

module "platform" {
  source = "../modules/platform"

  base_domain = var.base_domain
  # k3d publishes the cluster's :80 on this host port; Grafana has to know it
  # so its redirects do not drop back to :80.
  external_http_port = var.http_port

  git_repo_url    = var.git_repo_url
  github_token    = var.github_token
  github_username = var.github_username

  grafana_admin_password = var.grafana_admin_password
  prometheus_retention   = var.prometheus_retention
  enable_loki            = var.enable_loki
}
