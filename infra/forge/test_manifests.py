"""Offline checks of the Forge contract, including migration quota headroom."""

import json
import unittest

from render import ROOT, render


class ForgeContract(unittest.TestCase):
    def setUp(self):
        self.phases = render("a" * 40, "ghcr.io/onerandomd3v", "verified-class", "regcred")
        self.items = [item for phase in self.phases.values() for item in phase["items"]]
        self.workloads = [i for i in self.items if i["kind"] in {"Deployment", "StatefulSet", "Job"}]

    def test_namespace_services_storage(self):
        self.assertTrue(all(i["metadata"]["namespace"] == "team17" for i in self.items))
        services = {i["metadata"]["name"]: i for i in self.items if i["kind"] == "Service"}
        self.assertEqual(set(services), {"app", "api", "db"})
        self.assertTrue(all(i["spec"]["type"] == "ClusterIP" for i in services.values()))
        self.assertEqual(services["app"]["spec"]["ports"], [{"port": 80, "targetPort": 8080}])
        claims = [i for i in self.items if i["kind"] == "PersistentVolumeClaim"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["spec"]["resources"]["requests"]["storage"], "10Gi")
        self.assertEqual(claims[0]["spec"]["storageClassName"], "verified-class")
        self.assertFalse(any(i["kind"] in {"Secret", "Namespace", "ClusterRole", "Ingress"} for i in self.items))

    def test_quota_and_no_surge(self):
        totals = {"requests": {"cpu": 0, "memory": 0}, "limits": {"cpu": 0, "memory": 0}}
        for item in self.workloads:
            if item["kind"] == "Deployment":
                self.assertEqual(item["spec"]["strategy"]["type"], "Recreate")
                self.assertEqual(item["spec"]["replicas"], 1)
            pod = item["spec"]["template"]["spec"]
            self.assertFalse(pod.get("initContainers"))
            for c in pod["containers"]:
                for kind in totals:
                    totals[kind]["cpu"] += int(c["resources"][kind]["cpu"].removesuffix("m"))
                    totals[kind]["memory"] += int(c["resources"][kind]["memory"].removesuffix("Mi"))
        self.assertEqual(totals, {"requests": {"cpu": 375, "memory": 736}, "limits": {"cpu": 2000, "memory": 1952}})
        self.assertLessEqual(len(self.workloads), 10)

    def test_images_security_and_secrets(self):
        images = {}
        for item in self.workloads:
            pod = item["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertTrue(pod["securityContext"]["runAsNonRoot"])
            self.assertEqual(pod["imagePullSecrets"], [{"name": "regcred"}])
            self.assertEqual(pod["nodeSelector"]["kubernetes.io/arch"], "amd64")
            for c in pod["containers"]:
                self.assertTrue(c["image"].endswith(":" + "a" * 40))
                images[c["name"]] = c["image"]
                self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"])
                self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
                secret_keys = {e["name"] for e in c.get("env", []) if "secretKeyRef" in e.get("valueFrom", {})}
                if c["name"] in {"worker", "migrate"}:
                    self.assertEqual(secret_keys, {"BIPME_DATABASE_URL"})
        self.assertEqual(images["api"], images["worker"])
        self.assertEqual(images["api"], images["migrate"])

    def test_config_security_and_references(self):
        maps = {i["metadata"]["name"]: i["data"] for i in self.items if i["kind"] == "ConfigMap"}
        runtime = next(v for k, v in maps.items() if k.startswith("bipme-runtime-"))
        self.assertEqual(runtime["BIPME_AUTH_COOKIE_SECURE"], "true")
        self.assertEqual(runtime["BIPME_APP_ORIGIN"], "https://team17.xtradot.co")
        self.assertEqual(runtime["BIPME_EMBEDDING_PROVIDER"], "remote")
        self.assertNotIn("BIPME_EMBEDDING_REMOTE_URL", runtime)
        self.assertTrue(all(v == "false" for k, v in runtime.items() if k.endswith("ENABLED") or k.endswith("ALLOWED")))
        for item in self.workloads:
            pod = item["spec"]["template"]["spec"]
            for volume in pod["volumes"]:
                if "configMap" in volume:
                    self.assertIn(volume["configMap"]["name"], maps)
            for c in pod["containers"]:
                for source in c.get("envFrom", []):
                    self.assertIn(source["configMapRef"]["name"], maps)
        api = next(i for i in self.workloads if i["metadata"]["name"] == "api")
        c = api["spec"]["template"]["spec"]["containers"][0]
        self.assertIn("--no-proxy-headers", c["command"])
        self.assertIn("check_db.py", " ".join(c["readinessProbe"]["exec"]["command"]))
        self.assertEqual(c["livenessProbe"]["httpGet"]["path"], "/api/health")

    def test_bad_release_inputs(self):
        for sha in ("main", "latest", "a" * 7, "../bad"):
            with self.assertRaises(ValueError):
                render(sha, "ghcr.io/onerandomd3v", "verified-class")
        with self.assertRaises(ValueError):
            render("a" * 40, "ghcr.io/onerandomd3v", "")


if __name__ == "__main__":
    unittest.main()
