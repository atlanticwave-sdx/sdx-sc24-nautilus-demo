import yaml
import time
from kubernetes.stream import stream
from kubernetes import client, config, utils

APP_NAME = "amlight-sc24-demo"
NAMESPACE = "amlight"
COMMANDS = [
    "ping -c4 10.1.11.254",
]

with open("amlight-sc24-demo.yaml") as f:
    manifest = yaml.safe_load(f)

config.load_kube_config(config_file="~/.kube/config-nautilus")
app_v1 = client.AppsV1Api()
v1 = client.CoreV1Api()

print("-> Cleanup previous deployments")
resp = app_v1.list_namespaced_deployment(namespace=NAMESPACE, label_selector=f"app={APP_NAME}")
for dep in resp.items:
    print(f"--> removing deployment {dep.metadata.name}...")
    app_v1.delete_namespaced_deployment(name=dep.metadata.name, namespace=NAMESPACE)

print("--> waiting for deployment to be deleted...")
for _ in range(60):
    resp = v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={APP_NAME}")
    if len(resp.items) == 0:
        break
    time.sleep(2)
else:
     print("Timeout waiting for deployment to be deleted")

print("-> Creating deployment")
resp = app_v1.create_namespaced_deployment(body=manifest, namespace=NAMESPACE)

print("-> Waiting for deployment to be ready")
for _ in range(60):
    resp = v1.list_namespaced_pod(namespace=NAMESPACE, field_selector="status.phase=Running", label_selector=f"app={APP_NAME}")
    if len(resp.items) == 1:
        break
    time.sleep(2)
else:
     print("Timeout waiting for pod to be ready")

print("-> Running commands")
for cmd in COMMANDS:
    print(f"--> {cmd}")
    resp = stream(v1.connect_get_namespaced_pod_exec, resp.items[0].metadata.name, NAMESPACE, command=cmd.split(), container=APP_NAME, stderr=True, stdin=False, stdout=True, tty=False)
    print(resp)

# delete
print("-> Delete deployment")
app_v1.delete_namespaced_deployment(name=APP_NAME, namespace=NAMESPACE)
