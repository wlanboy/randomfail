## Helm install
This helm script installs the WebShell within a kubernetes cluster.

```bash
helm install randomfail . -n randomfail --create-namespace
```

```bash
kubectl get gateway,virtualservice -n randomfail
```

```bash
helm upgrade randomfail . -n randomfail 
```

```bash
helm uninstall randomfail -n randomfail
```
