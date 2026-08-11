# Argo CD — the component that actually makes previews appear and disappear.
#
# The ApplicationSet that generates preview Applications is intentionally NOT
# here; it is owned by platform/argocd/ and applied on top of this release. What
# this release does provide is the AppProject those Applications live in, so the
# ApplicationSet has something to reference the moment it is applied.
global:
  domain: ${argocd_host}

crds:
  install: true
  # Let `terraform destroy` / `make unbootstrap` actually clean up. Argo CD's
  # default (keep: true) leaves the CRDs orphaned in the cluster.
  keep: false

configs:
  params:
    # TLS terminates at ingress-nginx. Without this, nginx speaks HTTP to a
    # server that only speaks HTTPS and every request 502s / redirect-loops.
    server.insecure: ${argocd_insecure}
    # One repo, one cluster, a handful of apps: the defaults are oversized.
    controller.status.processors: "10"
    controller.operation.processors: "5"
    reposerver.parallelism.limit: "2"

  cm:
    # Previews should appear quickly after a push.
    timeout.reconciliation: 60s
    application.resourceTrackingMethod: annotation
    # Argo CD does not need to diff the noise Kubernetes adds to every object.
    resource.compareoptions: |
      ignoreAggregatedRoles: true

  rbac:
    # Read-only for anyone who is not admin. Local convenience, not a security
    # boundary — see the module README.
    policy.default: role:readonly

server:
  ingress:
    enabled: true
    controller: generic
    ingressClassName: ${ingress_class_name}
    hostname: ${argocd_host}
    path: /
    pathType: Prefix
    # No cert-manager locally. Phase 8 turns this on for EKS.
    tls: false
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: HTTP

  metrics:
    enabled: true
    serviceMonitor:
      enabled: true

  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      memory: 384Mi

controller:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      memory: 768Mi

repoServer:
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
  resources:
    requests:
      cpu: 50m
      memory: 192Mi
    limits:
      memory: 512Mi

applicationSet:
  enabled: true
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
  resources:
    requests:
      cpu: 25m
      memory: 96Mi
    limits:
      memory: 256Mi

redis:
  enabled: true
  metrics:
    enabled: true
    serviceMonitor:
      enabled: true
  resources:
    requests:
      cpu: 25m
      memory: 64Mi
    limits:
      memory: 192Mi

# No SSO and no notifications in the local stack: two fewer Deployments to feed.
dex:
  enabled: false

notifications:
  enabled: false

