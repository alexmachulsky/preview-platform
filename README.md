# Preview Platform

Ephemeral pull-request environments on Kubernetes.

**Open a PR → a real, isolated environment appears at a live URL → close the PR → it's gone.**

Nothing deletes the environment. It stops existing because the pull request stopped
existing, and Argo CD reconciles the cluster to match.

```
  PR opened
      ├─► GitHub Actions ── test ── build ──► ghcr.io/…/api:sha-abc1234
      │                                  └──► sticky PR comment with the URL
      └─► Argo CD ApplicationSet (pullRequest generator)
              └─► namespace preview-pr-42
                    api · worker · postgres · migrations · metrics · quota
  PR closed → Application pruned → namespace deleted
```

Environments are gated on a `preview` label, added when a PR opens and removed again
after three idle days. Reclaiming an abandoned preview and closing a pull request are
therefore the same operation, and neither one deletes anything directly — see
[the lifecycle](docs/architecture.md#lifecycle-the-label-is-the-switch).

## Stack

| Layer | Choice |
|---|---|
| CD | Argo CD `ApplicationSet` + `pullRequest` generator |
| CI | GitHub Actions → GHCR |
| IaC | Terraform (`helm`/`kubernetes` providers) |
| Cluster | k3d locally, EKS-ready |
| Ingress | ingress-nginx + wildcard `*.localtest.me` |
| Workload | FastAPI api + Python worker + Postgres |
| Observability | Prometheus + Grafana + Loki |

## Quickstart

```bash
make up          # create the k3d cluster
make bootstrap   # install the platform with Terraform
make urls        # where everything lives
```

Then open a pull request against this repo and watch `make previews`.

### Give Argo CD a GitHub token

Optional but strongly recommended. Without one the pull-request generator polls
anonymously, and GitHub's 60 requests/hour limit forces a 120-second interval that
still runs out if anything else on your IP uses the API.

Create a fine-grained PAT scoped to this repository with **Contents: read** and
**Pull requests: read**, then:

```bash
read -rsp 'PAT: ' T && printf 'github_token = "%s"\n' "$T" > infra/local/terraform.tfvars && unset T
make bootstrap
```

`*.tfvars` is gitignored.

### Two local-environment notes

**Ports.** The k3d load balancer binds host **8080/8443**, because Apache already owns
`:80` on this machine. Override with `make up HTTP_PORT=80 HTTPS_PORT=443` if yours is free.

**Wildcard DNS.** Preview hostnames need a domain that resolves any label to `127.0.0.1`.
The usual picks, `sslip.io` and `nip.io`, are **hijacked to `208.91.112.55` by the resolver
on this network**, so the platform uses `localtest.me` instead. Before changing
`BASE_DOMAIN`, confirm the replacement actually works:

```bash
getent ahostsv4 pr-1.$BASE_DOMAIN   # must print 127.0.0.1
```

Run `make help` for the full target list.

## Documentation

- [**Architecture**](docs/architecture.md) — the loop, the components, and the design
  decisions that are not obvious from the code
- [**Runbook**](docs/runbook.md) — every failure mode encountered building this, with
  the symptom that showed up first

## Roadmap

Deliberately out of scope for v1, in rough priority order: Kyverno admission policy to
*enforce* the signatures CI now produces, external-secrets for the database credential,
and `infra/aws` — VPC, EKS, ECR and a real wildcard domain, reusing the same platform
module.

Two items have come off this list. Reclaiming abandoned previews is built, as label
lifecycle rather than the TTL reaper originally sketched — a reaper that deleted
namespaces would have spent its life losing to `selfHeal`. Supply-chain scanning and
signing is built too: CI refuses to publish an image with a fixable HIGH or CRITICAL
vulnerability, and signs what it does publish. Nothing yet *requires* a signature at
admission time, which is what Kyverno would add.
