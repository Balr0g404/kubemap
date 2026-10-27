from kubemap.views.storage import build_storage


def test_pvc_size_and_users():
    res = {
        "pvcs": [{"metadata": {"name": "data", "namespace": "a"}, "spec": {"resources": {"requests": {"storage": "2Ti"}}, "storageClassName": "ssd"}, "status": {"phase": "Bound"}},
                 {"metadata": {"name": "tiny", "namespace": "a"}, "spec": {"resources": {"requests": {"storage": "1Gi"}}}, "status": {"phase": "Bound"}}],
        "pods": [{"metadata": {"name": "p", "namespace": "a"}, "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "data"}}]}}],
    }
    pvcs = build_storage(res)["pvcs"]
    assert [p["name"] for p in pvcs] == ["data", "tiny"]
    assert pvcs[0]["size"] == "2 Ti" and pvcs[0]["usedBy"] == ["p"] and pvcs[0]["storageClass"] == "ssd"


def test_cnpg_databases():
    res = {"cnpg_clusters": [{"metadata": {"name": "pg", "namespace": "tsdb"}, "spec": {"instances": 3, "storage": {"size": "2Ti"}, "imageName": "img:18"},
                              "status": {"readyInstances": 3, "phase": "Cluster in healthy state", "currentPrimary": "pg-6"}}]}
    (db,) = build_storage(res)["databases"]
    assert (db["instances"], db["ready"], db["primary"], db["storage"]) == (3, 3, "pg-6", "2Ti")


def test_secret_metadata_only_with_references():
    secret = {"metadata": {"name": "authsecret", "namespace": "simulation", "creationTimestamp": "2026-01-01T00:00:00Z", "labels": {"x": "y"}}}
    orphan = {"metadata": {"name": "old", "namespace": "simulation"}}
    res = {
        "secrets": [secret, orphan],
        "middlewares": [{"metadata": {"name": "auth", "namespace": "simulation"}, "spec": {"basicAuth": {"secret": "authsecret"}}}],
        "pods": [{"metadata": {"name": "p", "namespace": "simulation", "ownerReferences": [{"kind": "ReplicaSet", "name": "rs"}]},
                  "spec": {"volumes": [{"secret": {"secretName": "authsecret"}}], "imagePullSecrets": [{"name": "authsecret"}],
                           "containers": [{"name": "c", "image": "i", "env": [{"name": "A", "valueFrom": {"secretKeyRef": {"name": "authsecret", "key": "k"}}}], "envFrom": [{"secretRef": {"name": "authsecret"}}]}]}}],
        "ingressroutes": [{"metadata": {"name": "ir", "namespace": "simulation"}, "spec": {"tls": {"secretName": "authsecret"}}}],
    }
    secrets = {s["name"]: s for s in build_storage(res)["secrets"]}
    assert set(secrets["authsecret"]) == {"namespace", "name", "created", "labels", "usedBy", "unused"}
    kinds = {(u["kind"], u["name"]) for u in secrets["authsecret"]["usedBy"]}
    assert kinds == {("Middleware", "auth"), ("ReplicaSet", "rs"), ("IngressRoute", "ir")}
    assert secrets["authsecret"]["unused"] is False
    assert secrets["old"]["unused"] is True
