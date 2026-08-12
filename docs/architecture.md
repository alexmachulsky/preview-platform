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
         ├── NetworkPolicy   ×4, deny-by-default          wave -8
         └── ResourceQuota + LimitRange

  pull request closes → generator drops the entry → Application pruned → namespace gone
```

Because the Application owns the Namespace, pruning it takes the api, worker, database,
secret and quota with it. That is why the chart ships a `Namespace` object rather than
relying only on `CreateNamespace=true`.

## Lifecycle: the label is the switch

The generator lists only pull requests carrying the `preview` label, which makes one
label the platform's entire admission and reclamation policy:

| Event | Actor | Effect |
|---|---|---|
| PR opened or reopened | `preview-lifecycle` workflow | label added → environment appears |
| 3 days without activity | `preview-lifecycle` nightly cron | label removed → environment reclaimed |
| Comment `/preview` | `preview-lifecycle` workflow | label restored → environment returns |
| PR closed or merged | GitHub | PR leaves the list → environment gone |

Every row ends the same way: the PR's presence in the generator's result set changed, and
Argo CD reconciled. **No workflow, job or human ever deletes a namespace.**

That constraint is not aesthetic. The obvious design — a CronJob that deletes namespaces
older than a TTL — cannot work here, because `selfHeal` recreates anything removed behind
Argo CD's back. A reaper and the controller would fight on a three-minute cycle. Removing
the PR from the generator's input is the only teardown the controller agrees with.

Idleness is measured from the PR's `updated_at`, so a push, comment or review keeps an
environment alive. It reclaims *abandoned* branches, not old ones: a PR under review for
two weeks keeps its preview the whole time.

Fork pull requests are never labelled automatically. A preview runs the PR's code inside
the cluster, so building one from an untrusted fork hands a stranger a namespace next to
the platform's own services. Maintainers can label a fork PR by hand, which makes that a
reviewed decision rather than a default.

Setting `preview_label = ""` disables the whole mechanism and gives every open PR an
environment — fine on a quiet repository, but with no way to reclaim capacity.

## Isolation model

A preview runs code from a pull request next to every other preview. Two things
keep them apart, and each was added because the other is not sufficient on its own.

**Network.** Every preview namespace denies ingress and egress by default
(`templates/networkpolicy.yaml`), opening exactly four paths: ingress-nginx to the
api, monitoring to api and worker, and same-namespace pods to Postgres. Egress is DNS
plus the namespace itself — the workloads call nothing else, and images are pulled by
the kubelet rather than by the pod.

Without this, namespaces are only an organisational boundary. Any pod in the cluster
can dial any Service, so a preview's database is reachable from every other preview.

**Credential.** Each preview derives its Postgres password from
`sha256(namespace / release / seed)`. Determinism is forced: Argo CD's repo-server
renders with no cluster access, so anything random would mint a new password on every
sync while the running database still expected the old one.

Deterministic is fine; deterministic *from published inputs* is not. Namespace and
release are both `preview-pr-<N>`, so a seed committed to a public repo makes every
password computable by anyone. Terraform therefore generates the seed and passes it
through the ApplicationSet, so it exists only inside the cluster. The chart's committed
seed remains as the `helm install` fallback.

This matters more than it looks: `POSTGRES_USER` is a superuser in the official image,
so reaching the database is not merely read access — it is `COPY ... FROM PROGRAM`
inside the database container.

Rotating the seed only works because api, worker and postgres carry a
`checksum/db-credentials` annotation. Without it the Secret changes and nothing
restarts, leaving Postgres on the password it was initialised with.

**What is deliberately not defended.** Previews trust the pull request's code. Anything
that code can do inside its own namespace, it can do. The boundary is the namespace,
which is why fork pull requests do not get an environment without a maintainer
labelling them.

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
