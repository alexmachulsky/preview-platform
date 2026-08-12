# Runbook

Every entry here is a failure that actually happened while building this platform, with
the symptom that showed up first. They share a theme: the preview loop fails *quietly*.
Nothing pages you, the sync says `Progressing`, and the URL just 404s.

## Triage

```bash
make previews                                   # live preview namespaces + Applications
kubectl -n argocd get applicationset preview-environments \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status}: {.message}{"\n"}{end}'
kubectl -n argocd get app preview-pr-<N> \
  -o jsonpath='sync={.status.sync.status} health={.status.health.status}{"\n"}'
kubectl -n preview-pr-<N> get pods
```

---

## No preview appears at all

### The pull request has no `preview` label

The most likely cause, and the one that looks least like a fault: the generator lists
only labelled PRs, so an unlabelled one is invisible to it. Argo CD is working exactly as
configured and reports nothing wrong.

```bash
gh pr view <N> --json labels --jq '.labels[].name'
```

Add it back with a `/preview` comment on the PR, or directly:

```bash
gh pr edit <N> --add-label preview
```

Three things remove or withhold the label:

- **The nightly reaper** — no activity for 3 days. It always comments on the PR before
  unlabelling, so check the PR's timeline; if there is no such comment, this was not it.
- **A fork PR** — never labelled automatically, by design. Label it by hand after
  reviewing the diff.
- **The `label` job failed** on open. `gh run list --workflow preview-lifecycle.yaml`.

To confirm the filter itself is what the cluster is running:

```bash
kubectl -n argocd get applicationset preview-environments \
  -o jsonpath='{.spec.generators[0].pullRequest.github.labels}'
```

### The generator is rate-limited

```
ParametersGenerated=False: 403 API rate limit exceeded for <ip>
```

Unauthenticated GitHub allows **60 API requests/hour per IP**. A 30-second requeue needs
120/hr, so the generator works for roughly half an hour and then fails for the rest of
the window. No Application is created and nothing says why unless you read the
ApplicationSet conditions.

Without a token the platform floors the interval at 120s (30/hr). The real fix is a
token — 5,000/hr:

```bash
read -rsp 'PAT: ' T && printf 'github_token = "%s"\n' "$T" > infra/local/terraform.tfvars && unset T
make bootstrap
```

A fine-grained PAT scoped to this repository with **Contents: read** and
**Pull requests: read** is sufficient.

### The generator is pointed at the wrong repository

```
error listing repos: GET https://api.github.com/repos/git/preview-platform/pulls: 404
```

Owner `git` means something passed Argo CD's HTTPS auth username (`git` is the
convention for token auth) where the API owner belongs. Owner and repo are derived from
`git_repo_url`; check that variable, not `github_username`.

---

## The preview exists but the URL 404s

### First: do not health-check a preview with `/healthz`

```bash
curl -o /dev/null -w '%{http_code}\n' http://pr-99.localtest.me:8080/healthz   # 200
kubectl get ns preview-pr-99                                                   # NotFound
```

Both of those are correct. ingress-nginx's *default* server — the one that answers a
hostname matching no Ingress rule — serves its own `/healthz` with a 200 on port 80. The
path collides with the api's liveness endpoint, so probing it through the ingress passes
for a preview that was never created, one whose pods are all crashing, and one that is
perfectly healthy, indistinguishably.

Use `/version` instead. It exists only in the application, and its body names the PR:

```bash
curl -s http://pr-<N>.localtest.me:8080/version
# {"pr_number":"<N>","git_sha":"<head sha>", ...}
```

A 404 from nginx there means nothing is bound to that hostname; a JSON body naming a
*different* PR means DNS or the Ingress host is wrong. This distinction matters most in
scripts — a smoke test written against `/healthz` reports success forever.

### The api cannot reach its database after a platform change

```
psql: could not connect to server: Connection refused
```

Two causes, and they look identical from the pod.

**The credential rotated but the pod did not.** Changing `database.passwordSeed`
rewrites the Secret; Postgres keeps whatever password it was initialised with. The
`checksum/db-credentials` annotation on api, worker and postgres exists to force the
rollout — if a pod predates the Secret, it is running with the old DSN:

```bash
kubectl -n preview-pr-<N> get pod -l app.kubernetes.io/component=api \
  -o jsonpath='{.items[0].metadata.annotations.checksum/db-credentials}{"\n"}'
kubectl -n preview-pr-<N> get deploy -o jsonpath='{.items[0].spec.template.metadata.annotations}'
```

Different values mean the rollout has not landed yet. Wait, or
`kubectl rollout restart`.

**A NetworkPolicy is blocking it.** Confirm the policies are what you expect before
suspecting the application:

```bash
kubectl -n preview-pr-<N> get netpol
```

Four are expected: `default-deny`, `allow-api`, `allow-worker-metrics`,
`allow-postgres`. A connection from *outside* the namespace being refused is the
intended behaviour, not a fault — see the isolation model in the architecture doc. To
verify from inside, which is allowed:

```bash
kubectl -n preview-pr-<N> exec deploy/<release>-preview-app-api -- \
  python -c "import os,psycopg; psycopg.connect(os.environ['DATABASE_URL'].replace('+psycopg','')); print('ok')"
```

If a preview genuinely needs to call a third-party API, that is egress, and it is
denied by default: set `networkPolicy.allowExternalEgress: true`, accepting that it
re-opens the rest of the cluster too.

Note that these policies do nothing on a CNI that does not enforce NetworkPolicy. They
apply cleanly either way, so confirm enforcement rather than assuming it — k3s enforces
by default.

### Kyverno rejects an image CI just signed

```
resource Pod/preview-pr-<N>/... was blocked due to the following policies
verify-preview-images:
  require-cosign-signature: 'failed to verify image ...: no signatures found'
```

The confusing part is that `cosign verify` on the same digest succeeds from a
laptop. Both are right — they are looking in different places.

cosign v3 defaults to writing signatures as OCI 1.1 referrers. Kyverno reads the
legacy `sha256-<digest>.sig` tag unless `cosignOCI11` is set, and that flag is
experimental. The result is a signature that is real, verifiable and invisible to
the thing enforcing it.

Check where the signature actually landed:

```bash
cosign tree ghcr.io/<owner>/<repo>/api@sha256:<digest>
# "artifacts via OCI referrer" => Kyverno will not see it

curl -sI -H "Authorization: Bearer $TOKEN" \
  https://ghcr.io/v2/<owner>/<repo>/api/manifests/sha256-<digest>.sig
# 404 => the legacy tag Kyverno wants does not exist
```

CI signs with `--registry-referrers-mode=legacy` for this reason. If that flag is
lost, every preview fails admission while CI stays green — the signature step
still passes, because signing and verifying both work.

### Pods are stuck in ImagePullBackOff

Check which tag is actually requested:

```bash
kubectl -n preview-pr-<N> get pod -l app.kubernetes.io/component=api \
  -o jsonpath='{.items[0].spec.containers[0].image}{"\n"}'
gh api repos/<owner>/<repo>/pulls/<N> --jq '"sha-" + .head.sha'
```

**If the two disagree**, CD and CI are tagging differently. The ApplicationSet must use
`{{head_sha}}`, and CI must tag `github.event.pull_request.head.sha` — *not*
`GITHUB_SHA`, which on a `pull_request` event is a synthesised merge commit that exists
nowhere in the PR's history.

**If they agree and the pull still 403s**, the GHCR package is private. Packages pushed
by Actions are private by default even from a public repository:

```
failed to fetch anonymous token: 403 Forbidden
```

Make both packages public at
`github.com/users/<owner>/packages/container/<repo>%2Fapi/settings`, or configure an
`image.pullSecrets` entry.

**If they agree and the tag simply is not there**, CI has not finished. Argo CD retries
with backoff up to 5m and heals on its own.

### The ApplicationSet was edited but nothing changed

`terraform apply` reporting `0 changed` after editing `platform/argocd/` is expected and
wrong-looking. `helm_release` points at the chart by local path and the provider does
**not** diff on file contents. Bump `version:` in `platform/argocd/Chart.yaml`, or force
it:

```bash
terraform -chdir=infra/local apply -replace=module.platform.helm_release.preview_bootstrap
```

---

## The sync never finishes

```
Running: waiting for completion of hook batch/Job/preview-pr-<N>-preview-app-migrate
```

The migration Job is a sync hook, so Argo CD blocks on it. If the Job cannot start — a
bad image, a database that never became ready — the sync stays `Progressing` forever and
Argo CD keeps replaying the *stored* operation rather than re-rendering, so it will
recreate the Job with the **old** parameters even after you fix the cause.

Clear the stuck operation, then let it re-render:

```bash
kubectl -n argocd patch app preview-pr-<N> --type json -p '[{"op":"remove","path":"/operation"}]'
kubectl -n preview-pr-<N> delete job --all
kubectl -n argocd annotate app preview-pr-<N> argocd.argoproj.io/refresh=hard --overwrite
```

If it is still wrong, delete the Application; the ApplicationSet rebuilds it from
scratch within one requeue interval.

---

## A namespace is stuck Terminating

```
NamespaceFinalizersRemaining=True: argocd.argoproj.io/hook-finalizer in 1 resource instances
```

A deadlock. The hook Job carries Argo CD's finalizer, which blocks namespace deletion —
but Argo CD cannot remove it because the Application is itself pending deletion. Usually
follows a migration Job that never completed.

```bash
kubectl -n preview-pr-<N> patch job <job-name> \
  --type json -p '[{"op":"remove","path":"/metadata/finalizers"}]'
```

The namespace drains within about 10 seconds.

---

## Local development

### `docker compose up` dies with `DuplicateTable`

```
relation "widgets" already exists
```

Something created the schema without stamping `alembic_version`. Historically this was
the test suite pointing at the application's own database. Tests now own `preview_test`
and create it themselves. Reset:

```bash
docker compose down -v && docker compose up --build -d
```

### Tests skip instead of running

```
no database server behind postgresql+psycopg://…
```

Expected when nothing is listening. `docker compose up -d postgres` first, or set
`TEST_DATABASE_URL`. Each suite creates its own test database, so either can run alone.

### Preview hostnames do not resolve

```bash
getent ahostsv4 pr-1.localtest.me     # must print 127.0.0.1
```

`sslip.io` and `nip.io` — the usual choices — are hijacked to `208.91.112.55` by some
resolvers, including the one on the network this was built on. If `localtest.me` is also
blocked, any wildcard-to-loopback domain works; change `BASE_DOMAIN` and re-run
`make bootstrap`.

### Nothing is reachable on :8080

The k3d load balancer publishes host `8080/8443` because Apache owns `:80` on the
development machine. Check `docker port k3d-preview-platform-serverlb`, and rebuild with
`make up HTTP_PORT=80 HTTPS_PORT=443` if `:80` is free.

---

## Observability

### Prometheus is not scraping a preview

```bash
curl -sG http://prometheus.localtest.me:8080/api/v1/query \
  --data-urlencode 'query=up{namespace="preview-pr-<N>"}'
```

kube-prometheus-stack only selects ServiceMonitors carrying `release:
kube-prometheus-stack`, and preview namespaces are not known in advance — so
`serviceMonitorNamespaceSelector` must be `{}` and
`serviceMonitorSelectorNilUsesHelmValues` false. Both are set in the platform module; a
scrape gap usually means one was overridden.

### ServiceMonitors show OutOfSync but everything works

Cosmetic. The objects exist and the sync succeeded; Argo CD is diffing defaulted fields
on a CRD it renders without full schema knowledge. Confirm with
`kubectl -n preview-pr-<N> get servicemonitor` and the `up` query above.
