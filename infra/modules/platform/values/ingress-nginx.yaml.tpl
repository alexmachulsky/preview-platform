# ingress-nginx — the single front door for the whole platform.
#
# Service type is LoadBalancer on purpose: k3s ships the klipper "servicelb"
# controller, which turns a LoadBalancer Service into a host-port listener on
# every node. k3d's own load balancer container then forwards the host's
# published port onto :80/:443 of those nodes. NodePort would work too but the
# ports would not line up with the k3d port mapping.
controller:
  replicaCount: 1

  ingressClassResource:
    name: ${ingress_class_name}
    enabled: true
    # Every preview Ingress can omit ingressClassName and still be picked up.
    default: true
    controllerValue: k8s.io/ingress-nginx

  ingressClass: ${ingress_class_name}

  # Belt and braces: also reconcile Ingresses that carry neither the class name
  # nor the legacy annotation.
  watchIngressWithoutClass: true

  service:
    enabled: true
    type: LoadBalancer
    # Single-node-ish local cluster: Cluster policy keeps routing working no
    # matter which node the klipper pod answers on.
    externalTrafficPolicy: Cluster

  config:
    # nginx defaults worker-processes to "auto", i.e. one worker per *host* CPU
    # — the container's memory limit is respected but its CPU limit is not
    # visible to nginx. On a 64-core workstation that is 64 workers inside a
    # 512Mi cgroup, and the controller is OOMKilled during its first reload
    # with "pthread_create() failed (11: Resource temporarily unavailable)".
    # Pin it: this ingress serves a handful of preview environments.
    worker-processes: "${nginx_worker_processes}"
    max-worker-connections: "4096"

    # Preview URLs are proxied through the k3d load balancer, so the client IP
    # and scheme only survive in the forwarded headers.
    use-forwarded-headers: "true"
    compute-full-forwarded-for: "true"
    proxy-body-size: "32m"
    # Keep the log volume sane — everything here is scraped into Loki.
    log-format-escape-json: "true"

  metrics:
    enabled: true
    service:
      enabled: true
      labels:
        # Selector used by the ServiceMonitor that kube-prometheus-stack
        # creates for us (see values/kube-prometheus-stack.yaml.tpl). The
        # ServiceMonitor cannot live in this release: its CRD only arrives
        # with kube-prometheus-stack, which is installed *after* ingress-nginx.
        preview-platform.io/scrape: ingress-nginx
    # Deliberately NOT enabling controller.metrics.serviceMonitor here.
    serviceMonitor:
      enabled: false

  admissionWebhooks:
    enabled: true
    patch:
      enabled: true

  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      memory: 512Mi

# Nothing useful to serve on an unmatched host; nginx's own 404 is enough and
# it saves a Deployment.
defaultBackend:
  enabled: false
