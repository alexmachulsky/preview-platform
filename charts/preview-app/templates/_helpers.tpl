{{/* vim: set filetype=mustache: */}}

{{/*
Chart name, optionally overridden.
*/}}
{{- define "preview-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully qualified release name. Truncated at 63 chars for the DNS label limit.
*/}}
{{- define "preview-app.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "preview-app.api.fullname" -}}
{{- printf "%s-api" (include "preview-app.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "preview-app.worker.fullname" -}}
{{- printf "%s-worker" (include "preview-app.fullname" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Chart label, e.g. preview-app-0.1.0.
*/}}
{{- define "preview-app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Selector labels — the immutable subset. Never add anything version-dependent
here: it would make Deployment selectors unpatchable.
*/}}
{{- define "preview-app.selectorLabels" -}}
app.kubernetes.io/name: {{ include "preview-app.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Per-component selector labels. api and worker share name+instance and are told
apart by app.kubernetes.io/component, so neither Deployment can adopt the
other's pods.
*/}}
{{- define "preview-app.api.selectorLabels" -}}
{{ include "preview-app.selectorLabels" . }}
app.kubernetes.io/component: api
{{- end -}}

{{- define "preview-app.worker.selectorLabels" -}}
{{ include "preview-app.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end -}}

{{/*
Common labels for every object the chart creates.
*/}}
{{- define "preview-app.labels" -}}
helm.sh/chart: {{ include "preview-app.chart" . }}
{{ include "preview-app.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: {{ .Values.partOf }}
preview-platform/pr-number: {{ .Values.env.prNumber | quote }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
Common annotations, plus the caller's own. Usage:
  {{- include "preview-app.annotations" (dict "ctx" $ "extra" (dict "k" "v")) }}
*/}}
{{- define "preview-app.annotations" -}}
{{- $merged := merge (dict) (.extra | default dict) (.ctx.Values.commonAnnotations | default dict) -}}
{{- if $merged }}
{{- toYaml $merged }}
{{- end }}
{{- end -}}

{{/* ── Images ──────────────────────────────────────────────────────────── */}}

{{- define "preview-app.api.image" -}}
{{- $repo := .Values.api.image.repository | default (printf "%s/api" .Values.image.repository) -}}
{{- $tag := .Values.api.image.tag | default .Values.image.tag | default .Chart.AppVersion -}}
{{- if .Values.image.registry -}}
{{- printf "%s/%s:%s" .Values.image.registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{- define "preview-app.worker.image" -}}
{{- $repo := .Values.worker.image.repository | default (printf "%s/worker" .Values.image.repository) -}}
{{- $tag := .Values.worker.image.tag | default .Values.image.tag | default .Chart.AppVersion -}}
{{- if .Values.image.registry -}}
{{- printf "%s/%s:%s" .Values.image.registry $repo $tag -}}
{{- else -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end -}}

{{- define "preview-app.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets -}}
imagePullSecrets:
{{- range . }}
  - name: {{ . }}
{{- end }}
{{- end -}}
{{- end -}}

{{/* ── Security contexts ───────────────────────────────────────────────── */}}

{{- define "preview-app.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.securityContext.runAsUser }}
runAsGroup: {{ .Values.securityContext.runAsGroup }}
fsGroup: {{ .Values.securityContext.fsGroup }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "preview-app.containerSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .Values.securityContext.runAsUser }}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
privileged: false
capabilities:
  drop:
    - ALL
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* ── Database ────────────────────────────────────────────────────────── */}}

{{/*
Name of the postgresql subchart's primary Service. Mirrors the subchart's own
`common.names.fullname`, which is what `<release>-postgresql` comes from.
*/}}
{{- define "preview-app.postgresql.fullname" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- if $pg.fullnameOverride -}}
{{- $pg.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := $pg.nameOverride | default "postgresql" -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "preview-app.postgresql.port" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- $svc := $pg.service | default dict -}}
{{- $ports := $svc.ports | default dict -}}
{{- $ports.postgresql | default 5432 -}}
{{- end -}}

{{/*
Secret holding the database credentials. Derived from the release name, so the
Postgres StatefulSet and the workloads reach the same object without either
side being told about it.
*/}}
{{- define "preview-app.dbSecretName" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- $ext := .Values.externalDatabase | default dict -}}
{{- if and (not $pg.enabled) $ext.existingSecret -}}
{{- $ext.existingSecret -}}
{{- else -}}
{{- printf "%s-db" .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "preview-app.dbSecretUrlKey" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- $ext := .Values.externalDatabase | default dict -}}
{{- if and (not $pg.enabled) $ext.existingSecret -}}
{{- $ext.existingSecretKey | default "DATABASE_URL" -}}
{{- else -}}
{{- .Values.database.urlKey | default "DATABASE_URL" -}}
{{- end -}}
{{- end -}}

{{/*
Should the chart create the credentials Secret itself?
*/}}
{{- define "preview-app.createDbSecret" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- $ext := .Values.externalDatabase | default dict -}}
{{- if and (not $pg.enabled) $ext.existingSecret -}}
{{- else -}}
true
{{- end -}}
{{- end -}}

{{/*
Password for the `preview` user.

Derived deterministically from namespace + release + seed, so every render
produces the same value without needing to read anything from the cluster.

The obvious implementation — generate with randAlphaNum, then reuse the live
Secret's value via `lookup` — cannot work here. `lookup` returns nothing
whenever there is no cluster connection, and Argo CD's repo-server renders
exactly that way. Under GitOps every sync would therefore mint a *fresh*
password and write it to the Secret, while the running Postgres still only
accepts the one its data directory was initialised with. The api would start
failing authentication on a sync that changed nothing.

Deterministic derivation sidesteps that entirely: `helm install`, `helm
upgrade`, `helm template` and Argo CD all compute the identical string.

This suits a preview database that is unreachable outside its namespace and is
destroyed with its pull request. It is NOT a production pattern — the value is
recoverable by anyone who can read the chart and knows the release name. A real
environment should inject the password from external-secrets or SOPS via
`postgresql.auth.password`, which still takes precedence here.
*/}}
{{- define "preview-app.dbPassword" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- $auth := $pg.auth | default dict -}}
{{- with $auth.password -}}
{{- . -}}
{{- else -}}
{{- printf "%s/%s/%s" .Release.Namespace .Release.Name (.Values.database.passwordSeed | default "preview-app") | sha256sum | trunc (int .Values.database.passwordLength) -}}
{{- end -}}
{{- end -}}

{{/*
The DSN the application uses. psycopg3 driver form, as required by the api and
worker: postgresql+psycopg://preview:<password>@<release>-postgresql:5432/preview
*/}}
{{- define "preview-app.databaseUrl" -}}
{{- $pg := .Values.postgresql | default dict -}}
{{- $ext := .Values.externalDatabase | default dict -}}
{{- if $pg.enabled -}}
{{- $auth := $pg.auth | default dict -}}
{{- printf "postgresql+psycopg://%s:%s@%s:%v/%s"
      ($auth.username | default "preview")
      (include "preview-app.dbPassword" .)
      (include "preview-app.postgresql.fullname" .)
      (include "preview-app.postgresql.port" .)
      ($auth.database | default "preview") -}}
{{- else if $ext.url -}}
{{- $ext.url -}}
{{- else -}}
{{- printf "postgresql+psycopg://%s:%s@%s:%v/%s"
      ($ext.username | default "preview")
      ($ext.password | default "")
      ($ext.host | default (include "preview-app.postgresql.fullname" .))
      ($ext.port | default 5432)
      ($ext.database | default "preview") -}}
{{- end -}}
{{- end -}}

{{/* ── Workload environment ────────────────────────────────────────────── */}}

{{/*
Env shared by api, worker and both hook Jobs.
*/}}
{{- define "preview-app.commonEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "preview-app.dbSecretName" . }}
      key: {{ include "preview-app.dbSecretUrlKey" . }}
- name: GIT_SHA
  value: {{ .Values.env.gitSha | quote }}
- name: PR_NUMBER
  value: {{ .Values.env.prNumber | quote }}
- name: APP_ENV
  value: {{ .Values.env.appEnv | quote }}
- name: LOG_LEVEL
  value: {{ .Values.env.logLevel | quote }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/*
initContainer that blocks until the database accepts TCP connections. Uses the
api image, so it needs nothing beyond the Python standard library, and derives
host and port from DATABASE_URL so it cannot drift from the DSN.
*/}}
{{- define "preview-app.waitForDatabase" -}}
- name: wait-for-db
  image: {{ include "preview-app.api.image" . }}
  imagePullPolicy: {{ .Values.image.pullPolicy }}
  securityContext:
    {{- include "preview-app.containerSecurityContext" . | nindent 4 }}
  env:
    {{- include "preview-app.commonEnv" . | nindent 4 }}
    - name: WAIT_TIMEOUT_SECONDS
      value: {{ .Values.waitForDatabase.timeoutSeconds | quote }}
  command:
    - python
    - -c
    - |
      import os, socket, sys, time
      from urllib.parse import urlparse
      dsn = urlparse(os.environ["DATABASE_URL"])
      host, port = dsn.hostname, dsn.port or 5432
      deadline = time.monotonic() + float(os.environ.get("WAIT_TIMEOUT_SECONDS", "180"))
      while time.monotonic() < deadline:
          try:
              with socket.create_connection((host, port), timeout=3):
                  print(f"database {host}:{port} is accepting connections", flush=True)
                  sys.exit(0)
          except OSError as exc:
              print(f"waiting for {host}:{port} ({exc})", flush=True)
              time.sleep(3)
      sys.exit(f"timed out waiting for {host}:{port}")
  resources:
    requests:
      cpu: 10m
      memory: 32Mi
    limits:
      cpu: 100m
      memory: 128Mi
  volumeMounts:
    - name: tmp
      mountPath: /tmp
{{- end -}}
