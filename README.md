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

Run `make help` for the full target list. Architecture and troubleshooting live in
[`docs/`](docs/).
