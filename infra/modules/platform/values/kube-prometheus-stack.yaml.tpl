# kube-prometheus-stack — Prometheus, Alertmanager, Grafana, kube-state-metrics
# and node-exporter, trimmed to run next to the previews it is watching.
#
# Two things in here are load-bearing for the whole platform and must not be
# "cleaned up" later:
#
#   1. prometheusSpec.*SelectorNilUsesHelmValues = false together with the empty
#      *NamespaceSelector maps. Preview namespaces are created dynamically by
#      Argo CD and cannot be enumerated at install time, so Prometheus has to
#      select ServiceMonitors cluster-wide and without a release label filter.
#      With the chart defaults, a ServiceMonitor shipped by charts/preview-app
#      into preview-pr-42 is silently ignored.
#
#   2. prometheus.additionalServiceMonitors / additionalPodMonitors. These
#      monitor components installed by *other* Helm releases (ingress-nginx,
#      Loki, promtail). They live here because the ServiceMonitor CRD is
#      installed by this chart: putting them in their own release would create a
#      CRD ordering race.

crds:
  enabled: true

###############################################################################
# Scrape targets that do not exist on k3s
#
# k3s runs the controller-manager, scheduler, proxy and etcd inside the single
# k3s server process with no separately reachable metrics port. Leaving these
# enabled produces permanently-down targets and a wall of firing alerts.
###############################################################################
kubeControllerManager:
  enabled: false
kubeScheduler:
  enabled: false
kubeProxy:
  enabled: false
kubeEtcd:
  enabled: false

kubeApiServer:
  enabled: true
kubelet:
  enabled: true
coreDns:
  enabled: true

defaultRules:
  create: true
  rules:
    # Mirror the disabled scrape targets above, otherwise the rules alert on
    # components that were never meant to be there.
    etcd: false
    kubeProxy: false
    kubeControllerManager: false
    kubeSchedulerAlerting: false
    kubeSchedulerRecording: false
    windows: false

###############################################################################
# Prometheus
###############################################################################
prometheus:
  enabled: true

  ingress:
    enabled: true
    ingressClassName: ${ingress_class_name}
    hosts:
      - ${prometheus_host}
    paths:
      - /
    pathType: Prefix

  prometheusSpec:
    # Short retention on purpose. Storage is an emptyDir; this stack shares a
    # host with the preview environments it monitors.
    retention: ${prometheus_retention}
    retentionSize: ${prometheus_retention_size}
    walCompression: true
    scrapeInterval: 30s
    evaluationInterval: 30s

    # ---- Discovery across dynamically created preview namespaces ----
    # An empty (but non-null) namespace selector means "every namespace".
    # NilUsesHelmValues=false stops the chart from injecting
    # `release: kube-prometheus-stack` into the otherwise-empty selectors.
    serviceMonitorSelectorNilUsesHelmValues: false
    serviceMonitorSelector: {}
    serviceMonitorNamespaceSelector: {}

    podMonitorSelectorNilUsesHelmValues: false
    podMonitorSelector: {}
    podMonitorNamespaceSelector: {}

    probeSelectorNilUsesHelmValues: false
    probeSelector: {}
    probeNamespaceSelector: {}

    scrapeConfigSelectorNilUsesHelmValues: false
    scrapeConfigSelector: {}
    scrapeConfigNamespaceSelector: {}

    ruleSelectorNilUsesHelmValues: false
    ruleSelector: {}
    ruleNamespaceSelector: {}

    resources:
      requests:
        cpu: 100m
        memory: 400Mi
      limits:
        memory: 1800Mi

  # ---- Monitors for components owned by other Helm releases ----
  additionalServiceMonitors:
    - name: ingress-nginx-controller
      namespaceSelector:
        matchNames:
          - ${ingress_namespace}
      selector:
        matchLabels:
          preview-platform.io/scrape: ingress-nginx
      endpoints:
        - port: metrics
          interval: 30s
%{ if loki_enabled ~}
    - name: loki
      namespaceSelector:
        matchNames:
          - ${monitoring_namespace}
      selector:
        matchLabels:
          app: loki
          release: loki
      endpoints:
        - port: http-metrics
          interval: 30s
%{ endif ~}

%{ if loki_enabled ~}
  # promtail's chart ships no Service, so it is scraped straight off the pods.
  additionalPodMonitors:
    - name: promtail
      namespaceSelector:
        matchNames:
          - ${monitoring_namespace}
      selector:
        matchLabels:
          app.kubernetes.io/name: promtail
          app.kubernetes.io/instance: loki
      podMetricsEndpoints:
        - port: http-metrics
          interval: 30s
%{ endif ~}

###############################################################################
# Alertmanager — kept, but stateless
###############################################################################
alertmanager:
  enabled: true
  alertmanagerSpec:
    # No storage block at all => emptyDir. Silences do not survive a restart,
    # which is the right trade on an ephemeral local cluster.
    retention: 24h
    resources:
      requests:
        cpu: 10m
        memory: 64Mi
      limits:
        memory: 192Mi

###############################################################################
# Grafana
###############################################################################
grafana:
  enabled: true
  adminUser: ${grafana_admin_user}
  adminPassword: ${grafana_admin_password}

  defaultDashboardsEnabled: true
  defaultDashboardsTimezone: browser

  ingress:
    enabled: true
    ingressClassName: ${ingress_class_name}
    hosts:
      - ${grafana_host}
    path: /
    pathType: Prefix

  grafana.ini:
    server:
      # Must carry the externally visible port or every redirect (login, the
      # trailing-slash redirect on /) drops it and lands on :80.
      root_url: ${grafana_root_url}
    auth.anonymous:
      enabled: ${grafana_anonymous_enabled}
      org_name: Main Org.
      org_role: Viewer
    auth:
      disable_login_form: false
    analytics:
      check_for_updates: false
      reporting_enabled: false
    log:
      mode: console
      level: warn

  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      # Preview namespaces are not known in advance, and a later phase ships
      # dashboards as ConfigMaps from wherever it likes.
      searchNamespace: ALL
      provider:
        allowUiUpdates: true
    datasources:
      enabled: true
      defaultDatasourceEnabled: true

%{ if loki_enabled ~}
  additionalDataSources:
    - name: Loki
      uid: loki
      type: loki
      access: proxy
      url: ${loki_url}
      isDefault: false
      jsonData:
        maxLines: 1000
%{ endif ~}

  resources:
    requests:
      cpu: 50m
      memory: 160Mi
    limits:
      memory: 512Mi

###############################################################################
# Supporting components
###############################################################################
prometheusOperator:
  resources:
    requests:
      cpu: 50m
      memory: 96Mi
    limits:
      memory: 384Mi
  prometheusConfigReloader:
    resources:
      requests:
        cpu: 10m
        memory: 32Mi
      limits:
        memory: 96Mi

kubeStateMetrics:
  enabled: true

kube-state-metrics:
  resources:
    requests:
      cpu: 20m
      memory: 64Mi
    limits:
      memory: 192Mi

nodeExporter:
  enabled: true

prometheus-node-exporter:
  resources:
    requests:
      cpu: 20m
      memory: 32Mi
    limits:
      memory: 96Mi

# No Windows nodes and no Thanos on a k3d cluster.
windowsMonitoring:
  enabled: false

thanosRuler:
  enabled: false

# Alert rules shipped with the platform.
#
# Defined here rather than as a separate PrometheusRule object on purpose: this
# release installs the PrometheusRule CRD, so anything created alongside it is
# guaranteed to have a schema to validate against. A standalone
# kubernetes_manifest would need that CRD to exist at *plan* time, which it
# does not on a first apply.
additionalPrometheusRulesMap:
  preview-platform:
    groups:
      - name: preview-environments
        rules:
          - alert: PreviewHighErrorRate
            expr: |
              sum by (namespace) (rate(http_requests_total{namespace=~"preview-pr-.*",status="5xx"}[5m]))
                /
              clamp_min(sum by (namespace) (rate(http_requests_total{namespace=~"preview-pr-.*"}[5m])), 0.001)
                > 0.05
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "Preview {{ $labels.namespace }} is serving 5xx responses"
              description: >-
                More than 5% of requests in {{ $labels.namespace }} have failed
                for 5 minutes. This is a preview environment, so the usual cause
                is the pull request itself.

          - alert: PreviewWorkerStalled
            expr: |
              sum by (namespace) (rate(worker_jobs_processed_total{namespace=~"preview-pr-.*"}[10m])) == 0
                and
              sum by (namespace) (worker_poll_iterations_total{namespace=~"preview-pr-.*"}) > 0
            for: 15m
            labels:
              severity: info
            annotations:
              summary: "Preview {{ $labels.namespace }} worker has processed nothing for 15m"
              description: >-
                The worker is polling but completing no jobs. Idle previews look
                exactly like this, so it is informational rather than a warning.
