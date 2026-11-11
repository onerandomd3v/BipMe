"""Render an explicit SHA release locally. Never contacts Kubernetes or reads secrets."""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PHASES = ("foundation", "database", "migration", "workloads")


def render(sha, registry, storage_class, pull_secret=None):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("release must be a full lowercase Git SHA")
    if not re.fullmatch(r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9_./-]+", registry):
        raise ValueError("registry must include a lowercase repository prefix")
    for value in (storage_class, pull_secret):
        if value is not None and not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", value):
            raise ValueError("storage class and pull secret must be DNS names")
    if not storage_class:
        raise ValueError("supply the organizer-verified storage class")
    phases = {
        name: json.loads((ROOT / f"{name}.json").read_text()) for name in PHASES
    }
    configs = {
        "bipme-nginx": {
            "default.conf.template": (ROOT / "nginx.conf").read_text(),
            "bipme-api-proxy.conf.template": (ROOT / "proxy.conf").read_text(),
        },
        "bipme-checks": {"check_db.py": (ROOT / "check_db.py").read_text()},
    }
    for name, data in configs.items():
        phases["foundation"]["items"].append({
            "apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": name, "namespace": "team17"}, "data": data,
        })
    # Content-address ALL configmaps so rollback keeps the matching configuration.
    config_names = {}
    for item in phases["foundation"]["items"]:
        if item["kind"] == "ConfigMap":
            name = item["metadata"]["name"]
            digest = hashlib.sha256(json.dumps(item["data"], sort_keys=True).encode()).hexdigest()[:12]
            config_names[name] = f"{name}-{digest}"
            item["metadata"]["name"] = config_names[name]
        if item["kind"] == "PersistentVolumeClaim":
            item["spec"]["storageClassName"] = storage_class
    for phase in phases.values():
        for item in phase["items"]:
            if item["kind"] not in {"Deployment", "StatefulSet", "Job"}:
                continue
            item["metadata"]["name"] = item["metadata"]["name"].replace("RELEASE_SHA", sha[:12])
            pod = item["spec"]["template"]["spec"]
            if pull_secret:
                pod["imagePullSecrets"] = [{"name": pull_secret}]
            for container in pod["containers"]:
                image = container["image"].split(":")[0]
                container["image"] = f"{registry}/{image}:{sha}"
                container["imagePullPolicy"] = "IfNotPresent"
                for source in container.get("envFrom", []):
                    if "configMapRef" in source:
                        ref = source["configMapRef"]
                        ref["name"] = config_names[ref["name"]]
            for volume in pod.get("volumes", []):
                if "configMap" in volume:
                    ref = volume["configMap"]
                    ref["name"] = config_names[ref["name"]]
    return phases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--registry", default="ghcr.io/onerandomd3v")
    parser.add_argument("--storage-class", required=True)
    parser.add_argument("--pull-secret")
    parser.add_argument("--output", type=Path, default=ROOT / "rendered")
    args = parser.parse_args()
    phases = render(args.sha, args.registry, args.storage_class, args.pull_secret)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, manifest in phases.items():
        (args.output / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Rendered {args.sha}; no cluster access performed.")


if __name__ == "__main__":
    main()
