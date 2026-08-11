# Architecture

## The idea

Open a pull request and a complete, isolated copy of the stack appears at its own URL.
Close the pull request and it disappears.

The second half is the interesting one. Nothing tears the environment down. It stops
existing because the pull request stopped existing, and Argo CD reconciles the cluster
to match. There is no cleanup job to fail, no TTL to tune, and no orphaned namespace to
discover a month later.

## The loop

```
  ┌── developer opens / pushes to a pull request
  │
  ├──► GitHub Actions ──► test (api, worker) ──► build ──► ghcr.io/…/api:sha-<full>
  │                                                        ghcr.io/…/worker:sha-<full>
  │                                          └──► sticky PR comment with the URL
  │
  └──► Argo CD ApplicationSet · pullRequest generator
             │  polls the GitHub API, one parameter set per open PR
             ▼
       Application  preview-pr-<N>
         targetRevision  <head_sha>          ← the commit, never the branch
         path            charts/preview-app
         helm parameters image.tag, ingress.host, env.prNumber, env.gitSha
         syncPolicy      automated · prune · selfHeal · CreateNamespace
             │
             ▼
       Namespace  preview-pr-<N>
         ├── Secret          deterministic DSN                 wave -10
         ├── postgres        StatefulSet, emptyDir              wave -5
         ├── migrate Job     alembic upgrade head               wave  1
         ├── seed Job        idempotent demo data               wave  2
         ├── api             Deployment · Service · Ingress     wave  3
         ├── worker          Deployment
         ├── ServiceMonitor  ×2, scraped by Prometheus
         └── ResourceQuota + LimitRange

  pull request closes → generator drops the entry → Application pruned → namespace gone
```

Because the Application owns the Namespace, pruning it takes the api, worker, database,
secret and quota with it. That is why the chart ships a `Namespace` object rather than
relying only on `CreateNamespace=true`.

## Components

| Layer | Choice | Notes |
|---|---|---|
| Cluster | k3d (k3s in Docker) | Traefik disabled; ingress-nginx instead |
| Ingress | ingress-nginx | LoadBalancer via klipper, published on host `:8080` |
| DNS | `*.localtest.me` | Resolves any label to 127.0.0.1, no configuration |
| CD | Argo CD `ApplicationSet` | `pullRequest` generator, one Application per open PR |
| CI | GitHub Actions → GHCR | Matrix over api/worker, buildx with GHA cache |
| IaC | Terraform + `helm` provider | One `platform` module, reused by `local` and `aws` |
| Workload | FastAPI + Python worker + Postgres | Purpose-built; the platform is the project |
| Metrics | kube-prometheus-stack | ServiceMonitors selected across all namespaces |
| Logs | Loki + promtail | Both services log JSON |

## Design decisions worth knowing

**Terraform owns the inside of the cluster; the Makefile owns the cluster.**
There is no first-class k3d Terraform provider, so `make up` creates the cluster and
`make bootstrap` fills it. `infra/aws` reuses the identical `platform` module with EKS
underneath, so nothing about the platform is local-only.

**The AppProject and ApplicationSet are a separate Helm release from Argo CD.**
Both are instances of CRDs that the argo-cd chart installs, and Helm validates every
manifest in a release against the API server *before* installing any of it. Shipping
them inside that release can only ever fail on a fresh cluster with
`no matches for kind "AppProject"`. `depends_on` supplies the ordering.

**Previews are pinned to the full commit SHA, not a short one.**
`head_short_sha` is 8 characters in current Argo CD and has been 7 in the past. A tag
that disagrees with CI by one character does not fail loudly — the environment simply
sits in `ImagePullBackOff`. The full SHA cannot drift.

**CI tags the PR head commit, not `GITHUB_SHA`.**
On a `pull_request` event `GITHUB_SHA` is the merge commit Actions synthesised, which
exists nowhere in the PR's history. Argo CD asks for `head_sha`. Tagging with the wrong
one publishes an image no preview ever requests.

**The database password is derived, not generated.**
The obvious approach — `randAlphaNum` plus a `lookup` of the live Secret — cannot work
under GitOps. `lookup` returns nothing without a cluster connection and Argo CD's
repo-server renders exactly that way, so every sync would mint a fresh password while
the running Postgres still expected the old one. The password is instead a hash of
namespace + release + seed, identical from every renderer. Fine for a preview database
that is unreachable outside its namespace and dies with its PR; **not** a production
pattern. Set `postgresql.auth.password` to inject a real secret.

**Postgres is first-party, not the Bitnami subchart.**
Bitnami withdrew every versioned tag of `bitnami/postgresql` from Docker Hub — only
`latest` and signature tags remain, and the 3948 version tags moved to `bitnamilegacy/`.
The subchart could therefore only resolve to an unpinnable `:latest`. The bundled
StatefulSet runs `postgres:16-alpine`, the same image docker-compose uses, so local and
preview environments share one database build.

**Persistence is off.** A preview holds nothing worth keeping, and a PVC that outlives
its pull request is exactly the garbage this platform exists to prevent.

## Repository layout

```
apps/api          FastAPI: widgets/jobs, health probes, /metrics, PR landing page
apps/worker       claims jobs with FOR UPDATE SKIP LOCKED, exports counters
charts/preview-app        the environment, rendered once per pull request
platform/argocd           AppProject + ApplicationSet (its own Helm release)
infra/modules/platform    ingress-nginx, Argo CD, Prometheus, Grafana, Loki
infra/local               targets k3d
infra/aws                 phase 8: VPC + EKS + ECR, same platform module
```

## What this is not

Single-replica everything, no TLS, no authentication on the preview URLs, and a
password recoverable from the chart. Those are correct for ephemeral environments on a
laptop and wrong for anything else. The roadmap items — Trivy and Cosign in CI, Kyverno
admission policy, external-secrets, and a TTL reaper for environments whose PR was
force-abandoned — are where that gap closes.
