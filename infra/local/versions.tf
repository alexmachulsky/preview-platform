terraform {
  required_version = ">= 1.5.0"

  # Local backend on purpose. The cluster this state describes is itself
  # disposable (`make down` throws it away), so there is nothing worth the
  # operational weight of a remote backend. infra/aws/ is where that changes.
  backend "local" {
    path = "terraform.tfstate"
  }

  required_providers {
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.13.0, < 3.0.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.30.0, < 3.0.0"
    }
  }
}

###############################################################################
# Providers
#
# The k3d cluster is created outside Terraform by `make up`, so both providers
# read an existing kubeconfig context directly. No data source, no
# `depends_on` on a cluster resource: a data source lookup would run during
# plan against an empty state and fail before the first apply could create
# anything.
###############################################################################

provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kube_context
}

provider "helm" {
  kubernetes {
    config_path    = var.kubeconfig_path
    config_context = var.kube_context
  }
}
