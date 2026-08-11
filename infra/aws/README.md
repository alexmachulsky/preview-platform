# `infra/aws` — planned (phase 8)

**Nothing is provisioned here yet.** This directory is a placeholder that
records the shape of the AWS root module so the local stack is built in a way
that can actually be lifted onto EKS, rather than discovering the differences
later.

There are no `.tf` files on purpose: an empty-but-real Terraform root module is
worse than none, because `terraform init` in CI would start creating state for
infrastructure nobody asked for.

## The point

`infra/modules/platform` is the deliverable that gets reused. `infra/local` and
this directory are two thin root modules that configure providers and hand the
same module a different `base_domain`:

```
                    infra/modules/platform
                    (ingress-nginx, Argo CD,
                     kube-prometheus-stack, Loki)
                       ▲                  ▲
                       │                  │
      infra/local ─────┘                  └───── infra/aws
      k3d, localtest.me,                  EKS, a real Route 53 zone,
      no TLS, port 8080                   real TLS, port 443
```

Everything below EKS (VPC, registry, CI identity) is new; everything above it
is the module that already exists.

## What phase 8 adds

### 1. Network — `terraform-aws-modules/vpc/aws`

Three AZs, public + private subnets, a single NAT gateway (cost, not
resilience). Subnets carry the `kubernetes.io/role/elb` and
`kubernetes.io/role/internal-elb` tags so the AWS Load Balancer Controller can
discover them.

### 2. Cluster — `terraform-aws-modules/eks/aws`

One managed node group on spot instances, private API endpoint plus a
restricted public endpoint, and EKS Pod Identity / IRSA enabled — that is the
prerequisite for the controllers below to get AWS permissions without static
credentials.

Add-ons: `vpc-cni`, `coredns`, `kube-proxy`, `aws-ebs-csi-driver` (Prometheus
gets a real PVC on EKS instead of the `emptyDir` it uses locally).

### 3. Registry — ECR

One repository per service (`preview-platform/api`, `preview-platform/worker`)
with a lifecycle policy that expires untagged images after a few days.
Preview images are per-commit and pile up fast.

The local stack uses GHCR instead; the only thing that changes is the image
repository value passed to `charts/preview-app`.

### 4. CI identity — GitHub OIDC

An `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com`
plus a role whose trust policy is scoped to
`repo:alexmachulsky/preview-platform:*`. GitHub Actions then pushes to ECR with
a short-lived token and **no long-lived AWS keys in repository secrets**. This
is the main reason to do the AWS side properly at all.

### 5. The same platform module

```hcl
module "platform" {
  source = "../modules/platform"

  base_domain        = "preview.example.com"   # a real Route 53 zone
  external_http_port = 443
  argocd_insecure    = true                    # TLS still terminates at the ingress
  github_token       = var.github_token

  # Real disks and a real retention window once storage is not an emptyDir.
  prometheus_retention = "15d"
}
```

The module needs no changes. `argocd_insecure` stays `true` because TLS
continues to terminate at the ingress — what changes is that the certificate is
real.

### 6. What is genuinely local-only

| Concern | `infra/local` | `infra/aws` |
|---|---|---|
| DNS | `localtest.me` wildcard → loopback | Route 53 zone + **external-dns** |
| TLS | none, plain HTTP on `:8080` | **cert-manager** + Let's Encrypt DNS-01 |
| Ingress address | k3s `klipper` host port via the k3d LB | NLB from the AWS Load Balancer Controller |
| Prometheus storage | `emptyDir`, 6h | EBS `gp3` PVC, 15d |
| Auth | anonymous Grafana viewer, `admin`/`admin` | SSO; anonymous access off |

`external-dns` and `cert-manager` are the two additions that must go into the
platform module rather than this root module, behind feature flags
(`enable_external_dns`, `enable_cert_manager`), so the local stack keeps
skipping them. Both need IRSA roles created here and passed in as service
account annotations.

### 7. State

S3 backend with DynamoDB (or S3 native) locking, and a workspace per
environment. `infra/local` keeps its local backend — that state describes a
cluster that `make down` deletes anyway.

## Ordering constraint carried over from local

The platform module configures no providers of its own. On EKS the `kubernetes`
and `helm` providers must be configured from the `aws_eks_cluster` outputs, and
that provider configuration is evaluated **during plan** — so the cluster and
the platform cannot live in one `terraform apply` from an empty state. Phase 8
splits them:

```
infra/aws/cluster/    VPC + EKS + ECR + OIDC        (apply first)
infra/aws/platform/   providers from remote state,  (apply second)
                      module "platform"
```

This is the same class of problem as the CRD race documented in
`infra/modules/platform/README.md`, one layer down.
