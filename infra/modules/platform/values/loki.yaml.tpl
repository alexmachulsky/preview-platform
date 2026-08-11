# loki-stack — Loki plus promtail, no Grafana of its own.
#
# Grafana comes from kube-prometheus-stack and the Loki datasource is
# provisioned there (grafana.additionalDataSources), so this release must not
# also emit a datasource ConfigMap or the two definitions collide on the name.
loki:
  enabled: true
  # kube-prometheus-stack's Grafana already owns the default datasource.
  isDefault: false

  # Ephemeral cluster, ephemeral logs.
  persistence:
    enabled: false

  # The ServiceMonitor for Loki is created by kube-prometheus-stack (which owns
  # the CRD), not here. See values/kube-prometheus-stack.yaml.tpl.
  serviceMonitor:
    enabled: false

  config:
    table_manager:
      retention_deletes_enabled: true
      retention_period: ${loki_retention_hours}h
    limits_config:
      enforce_metric_name: false
      reject_old_samples: true
      reject_old_samples_max_age: 168h
      # Previews can be chatty on startup; the defaults rate-limit them away.
      ingestion_rate_mb: 8
      ingestion_burst_size_mb: 16
    chunk_store_config:
      max_look_back_period: ${loki_retention_hours}h

  resources:
    requests:
      cpu: 50m
      memory: 192Mi
    limits:
      memory: 640Mi

promtail:
  enabled: true
  serviceMonitor:
    enabled: false
  resources:
    requests:
      cpu: 20m
      memory: 64Mi
    limits:
      memory: 192Mi

grafana:
  enabled: false
  sidecar:
    datasources:
      # Suppress the datasource ConfigMap this chart would otherwise create.
      enabled: false

prometheus:
  enabled: false

fluent-bit:
  enabled: false

filebeat:
  enabled: false

logstash:
  enabled: false

test_pod:
  enabled: false
