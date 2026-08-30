# Helm Chart: randomfail

Helm Chart für das Deployment des `randomfail`-Chaos-Containers in Kubernetes.
Der Chart unterstützt wahlweise Istio (Standard) oder Traefik als Ingress-Weg,
gesteuert über den Schalter `ingress.controller`.

## Überblick

| Eigenschaft | Wert |
|---|---|
| Chart-Name | `randomfail` |
| Chart-Version | 0.1.0 |
| App-Version | `latest` |
| Typ | `application` |

## Komponenten

Das Chart rendert folgende Kubernetes-Ressourcen:

- **Deployment** (`templates/deployment.yaml`) – 1 Replica des Containers `wlanboy/randomfail`, mit Startup-, Liveness- und Readiness-Probe (`/healthz`, `/readyz`) sowie den `CHAOS_*`-Umgebungsvariablen für die Fehlerinjektion.
- **PersistentVolumeClaim** (`templates/pvc.yaml`, nur bei `pvc.enabled: true`) – wird als `/tmp`-Volume gemountet, u. a. für `DISK_FILL`-Chaos.
- **Service** (`templates/service.yaml`) – ClusterIP-Service, leitet Traffic an die Pods weiter.
- **Gateway** (`templates/gateway.yaml`, nur bei `ingress.controller: istio`) – Istio `Gateway` auf Port 80/HTTP und optional 443/HTTPS (bei `certManager.enabled: true`) für die konfigurierten Hosts.
- **VirtualService** (`templates/virtualservice.yaml`, nur bei `ingress.controller: istio`) – Istio `VirtualService`, routet Traffic vom Gateway (und dem internen `mesh`-Gateway) zum Service.
- **IngressRoute** (`templates/traefik-ingressroute.yaml`, nur bei `ingress.controller: traefik`) – Traefik `IngressRoute`, routet die konfigurierten Hosts direkt zum Service.
- **Certificate** (`templates/certificate.yaml`, nur bei `certManager.enabled: true`) – cert-manager `Certificate`, stellt das TLS-Secret für das Istio-Gateway bereit.

Welche Ingress-Ressource gerendert wird, steuert `ingress.controller`
(`istio` | `traefik` | `none`). Zusätzlich zum Werte-Schalter prüft jedes
Ingress-Template über `.Capabilities.APIVersions.Has`, ob die passende CRD im
Zielcluster überhaupt vorhanden ist – ein `helm install`/`helm template`
schlägt also nicht fehl, nur weil die CRDs des jeweils anderen Controllers
fehlen.

## Konfiguration (`values.yaml`)

| Key | Beschreibung | Default |
|---|---|---|
| `image.repository` / `image.tag` / `image.pullPolicy` | Container-Image | `wlanboy/randomfail`, `latest`, `IfNotPresent` |
| `replicaCount` | Anzahl Replicas | `1` |
| `deploymentName` | Name für Deployment und Ingress-Ressourcen | `randomfail` |
| `service.name` | Name des Service-Objekts | `randomfail-svc` |
| `service.type` | Service-Typ | `ClusterIP` |
| `service.port` / `service.targetPort` | Service- und Container-Port | `8080` |
| `pvc.enabled` | PVC für `/tmp` anlegen | `true` |
| `pvc.name` / `pvc.accessModes` / `pvc.storageClassName` / `pvc.size` | PVC-Einstellungen | `randomfail-tmp-pvc`, `[ReadWriteOnce]`, `""`, `100Mi` |
| `volume.mountPath` | Mountpfad des `/tmp`-Volumes im Container | `/tmp` |
| `chaos.*` | Steuerung der Chaos-Umgebungsvariablen (Intervall, Startup-Delay, Memory/Disk/CPU-Chaos, Slow-Response, SIGTERM-Delay, Readiness-Flap) | siehe `values.yaml` |
| `ingress.controller` | Aktiver Ingress-Weg: `istio`, `traefik` oder `none` | `istio` |
| `ingress.hosts` | Liste externer Hostnamen für den Ingress (gilt für beide Controller) | `randomfail.tp.lan`, `randomfail.gmk.lan`, `randomfail.localhost` |
| `istio.gatewayName` | Name des Istio-Gateway-Objekts | `randomfail-gw` |
| `istio.gatewayNamespace` | Namespace, in dem das TLS-Secret für das Gateway liegt | `istio-ingress` |
| `istio.tls.enabled` / `istio.tls.secretName` | TLS-Konfiguration des Gateways | `true`, `randomfail-tls` |
| `traefik.entryPoints` | Traefik Entrypoints für die IngressRoute | `[web, websecure]` |
| `certManager.enabled` | cert-manager `Certificate` für das Istio-TLS-Secret erzeugen | `true` |
| `certManager.issuerRef.kind` / `certManager.issuerRef.name` | cert-manager Issuer-Referenz | `ClusterIssuer`, `local-ca-issuer` |
| `certManager.dnsNames` | SANs für das Zertifikat | `randomfail.tp.lan`, `randomfail.gmk.lan`, `randomfail.localhost` |

Für die Wahl des Controllers stehen zwei schlanke Override-Dateien bereit,
statt `ingress.controller` von Hand setzen zu müssen:
[values-istio.yaml](values-istio.yaml) und
[values-traefik.yaml](values-traefik.yaml). Letztere deaktiviert zusätzlich
`certManager.enabled`, da das erzeugte Zertifikat ausschließlich vom
Istio-Gateway konsumiert wird und bei `ingress.controller: traefik`
ungenutzt bliebe.

## Installation

Mit Istio (Standard):

```bash
kubectl create namespace randomfail
kubectl label namespace randomfail istio-injection=enabled --overwrite
helm install randomfail ./randomfail-chart -n randomfail --create-namespace -f randomfail-chart/values-istio.yaml
```

Mit Traefik:

```bash
helm install randomfail ./randomfail-chart -n randomfail --create-namespace -f randomfail-chart/values-traefik.yaml

helm status randomfail -n randomfail
```

Das `istio-injection`-Label wird nur benötigt, wenn `ingress.controller:
istio` aktiv ist (der Pod erhält sonst keinen Sidecar, obwohl das
Deployment-Template `sidecar.istio.io/inject: "true"` setzt).

```bash
kubectl get gateway,virtualservice -n randomfail       # bei ingress.controller: istio
kubectl get ingressroute -n randomfail                 # bei ingress.controller: traefik
```

## Upgrade

```bash
helm upgrade randomfail ./randomfail-chart -n randomfail --create-namespace
```

Bei geänderten Values (z. B. anderes Image-Tag oder Wechsel des Ingress-Controllers):

```bash
helm upgrade randomfail ./randomfail-chart -n randomfail --set image.tag=1.2.3
helm upgrade randomfail ./randomfail-chart -n randomfail -f randomfail-chart/values-traefik.yaml
```

## Deinstallation

```bash
helm uninstall randomfail -n randomfail
```

> Der PVC (`pvc.name`) wird von Helm nicht automatisch gelöscht, sofern er
> nicht Teil der gerenderten Ressourcen des Release ist – Standardverhalten
> von Kubernetes-PVCs unter Helm ist, dass sie mit deinstalliert werden, da
> sie Teil des Charts sind. Prüfe nach der Deinstallation mit
> `kubectl get pvc -n randomfail`, ob Aufräumbedarf besteht.

## Hinweise

- Der Gateway-Selector ist im Template fest auf `istio: ingressgateway` gesetzt (kein Values-Override vorgesehen).
- Der VirtualService exportiert die Route auf `.` (eigener Namespace), `istio-ingress` und `istio-system` und bindet sowohl das eigene Gateway als auch `mesh` (für internen Traffic innerhalb des Meshes) ein.
- Bei `ingress.controller: traefik` wird kein Mesh-Routing für internen Traffic benötigt – die IngressRoute deckt nur externen Traffic über die konfigurierten Hosts ab.
- Die IngressRoute setzt kein eigenes `tls`-Feld – `websecure` in `traefik.entryPoints` reicht aus, sofern der Cluster den Entrypoint per `--entryPoints.websecure.http.tls=true` und eine `TLSStore` mit `defaultCertificate` bereitstellt. In Clustern ohne Default-Zertifikat schlägt der TLS-Handshake fehl bzw. es wird ein selbstsigniertes Traefik-Zertifikat verwendet.
- Bei `ingress.controller: none` wird keine Ingress-Ressource gerendert; Deployment, Service und (falls aktiviert) PVC/Certificate laufen weiter.
- `certManager.enabled` und `ingress.controller` sind unabhängige Schalter: Das Zertifikat wird nur vom Istio-Gateway referenziert, kann bei Bedarf aber auch unabhängig davon aktiviert/deaktiviert werden.

## Testen

```bash
# Istio-Pfad rendern
helm template randomfail ./randomfail-chart -f randomfail-chart/values-istio.yaml --show-only templates/virtualservice.yaml

# Traefik-Pfad rendern
helm template randomfail ./randomfail-chart -f randomfail-chart/values-traefik.yaml --show-only templates/traefik-ingressroute.yaml

# sicherstellen, dass bei controller=none keine Ingress-Ressourcen entstehen
helm template randomfail ./randomfail-chart --set ingress.controller=none | grep -E "IngressRoute|VirtualService|Gateway"

helm lint ./randomfail-chart -f randomfail-chart/values-istio.yaml
helm lint ./randomfail-chart -f randomfail-chart/values-traefik.yaml
```
