import os
import json
import time
from kubernetes import client, config, utils
from kubernetes.stream import stream

config.load_kube_config(config_file=os.getenv("KUBECONFIG", "~/work/fabric_config/kubeconfig-nautilus"))

k8s_client = client.ApiClient()
app_v1 = client.AppsV1Api()
v1 = client.CoreV1Api()
k8s_custom = client.CustomObjectsApi(k8s_client)

NAMESPACE = "amlight"

KNOWN_PODS = {}

def reload_config():
    global k8s_client, app_v1, v1, k8s_client

    config.load_kube_config(config_file=os.getenv("KUBECONFIG", "~/.kube/config-nautilus"))
    k8s_client = client.ApiClient()
    app_v1 = client.AppsV1Api()
    v1 = client.CoreV1Api()
    k8s_custom = client.CustomObjectsApi(k8s_client)
    

def delete_vlan(vlan):
    try:
        resp = k8s_custom.delete_namespaced_custom_object(group="k8s.cni.cncf.io", version="v1", namespace=NAMESPACE, plural="network-attachment-definitions", name=f"multus{vlan}")
    except client.exceptions.ApiException as exc:
        print(f"Failed to delete network-attachment-definition 'multus{vlan}': {exc}")
        return False
    # TODO: wait to remove?
    return True

def create_vlan(iface, vlan):
    try:
        resp = k8s_custom.get_namespaced_custom_object(group="k8s.cni.cncf.io", version="v1", namespace=NAMESPACE, plural="network-attachment-definitions", name=f"multus{vlan}")
    except client.exceptions.ApiException:
        pass
    else:
        if not delete_vlan(vlan):
            return False

    net_dict = {
        'apiVersion': 'k8s.cni.cncf.io/v1',
        'kind': 'NetworkAttachmentDefinition',
        'metadata': {
            'name': f'multus{vlan}',
            'namespace': NAMESPACE,
        }, 
        'spec': {
            'config': json.dumps({
                "cniVersion": "0.3.1",
                "name": f"multus{vlan}",
                "plugins": [{
                    "name": f"multus{vlan}",
                    "type": "vlan",
                    "master": iface,
                    "vlanId": vlan,
                    "ipam": {
                        "type": "host-local",
                        "subnet": "10.1.11.0/24",
                        "rangeStart": "10.1.11.10",
                        "rangeEnd": "10.1.11.200"
                    }
                }]
            }),
        },
    }

    try:
        resp = k8s_custom.create_namespaced_custom_object(group="k8s.cni.cncf.io", version="v1", namespace=NAMESPACE, plural="network-attachment-definitions", body=net_dict)
    except client.exceptions.ApiException as exc:
        print(f"Failed to create network-attachment-definition 'multus{vlan}': {exc}")
        return False

    return True

def delete_deployment(name):
    app_v1.delete_namespaced_deployment(name=name, namespace=NAMESPACE)
    for _ in range(60):
        resp = v1.list_namespaced_pod(namespace=NAMESPACE, label_selector=f"app={name}")
        if len(resp.items) == 0:
            break
        time.sleep(2)
    else:
        print("Timeout waiting for deployment to be deleted")
        return False
    return True

def create_deployment(
    name="amlight-demo",
    image="gitlab-registry.nrp-nautilus.io/prp/perfsonar/testpoint",
    nrp_node="k8s-gen4-01.ampath.net",
    node_iface="enp193s0f1",
    vlan=3888
):
    try:
        resp = app_v1.read_namespaced_deployment(namespace=NAMESPACE, name=name)
    except client.exceptions.ApiException:
        pass
    else:
        if not delete_deployment(name):
            return False

    if node_iface and vlan:
        create_vlan(node_iface, vlan)

    deploy_dict = {
        'apiVersion': 'apps/v1',
        'kind': 'Deployment',
        'metadata': {
            'name': name,
            'namespace': NAMESPACE, 
            'labels': {'app': name},
        },
        'spec': {
            'replicas': 1, 
            'selector': {
                'matchLabels': {'app': name}
            },
            'template': {
                'metadata': {
                    'name': name,
                    'labels': {
                        'app': name
                    },
                    'annotations': {
                        'k8s.v1.cni.cncf.io/networks': '[ { "name": "multus%s" } ]' % (vlan)
                    }
                },
                'spec': {
                    'affinity': {
                        'nodeAffinity': {
                            'requiredDuringSchedulingIgnoredDuringExecution': {
                                'nodeSelectorTerms': [{
                                    'matchExpressions': [{
                                        'key': 'kubernetes.io/hostname',
                                        'operator': 'In',
                                        'values': [nrp_node]
                                    }]
                                }]
                            }
                        }
                    },
                    'tolerations': [
                        {
                            'effect': 'NoSchedule',
                            'key': 'nautilus.io/ceph',
                            'operator': 'Exists'
                        },
                        {
                            'effect': 'PreferNoSchedule',
                            'key': 'vidia.com/gpu',
                            'operator': 'Exists'
                        }
                    ],
                    'containers': [
                        {
                            'name': name,
                            'image': image,
                            'resources': {
                                'limits': {'memory': '1Gi', 'cpu': '16m'},
                                'requests': {'memory': '1Gi', 'cpu': '16m'}
                            },
                            'args': ['sh', '-c', 'sleep infinity'],
                            'securityContext': {
                                'capabilities': {'add': ['NET_ADMIN']}
                            }
                        },
                    ]
                }
            }
        }
    }

    resp = app_v1.create_namespaced_deployment(namespace=NAMESPACE, body=deploy_dict)

    return True


def wait_for_pod_ready(name="amlight-demo"):
    print("wait for resources to be ready...", end="")
    for _ in range(60):
        resp = v1.list_namespaced_pod(namespace=NAMESPACE, field_selector="status.phase=Running", label_selector=f"app={name}")
        if len(resp.items) == 1:
            break
        print(".", end="")
        time.sleep(2)
    else:
        print("Timeout waiting for pod to be ready")
        return False

    print(" done")
    return True


def run_command(name, cmd):
    if name not in KNOWN_PODS:
        resp = v1.list_namespaced_pod(namespace=NAMESPACE, field_selector="status.phase=Running", label_selector=f"app={name}")
        if len(resp.items) != 1:
            print("Pod/Deployment not found")
            return False
        KNOWN_PODS[name] = resp.items[0].metadata.name
    resp = stream(v1.connect_get_namespaced_pod_exec, KNOWN_PODS[name], NAMESPACE, command=cmd.split(), stderr=True, stdin=False, stdout=True, tty=False)
    return resp
