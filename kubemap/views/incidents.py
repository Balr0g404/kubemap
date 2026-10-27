from datetime import datetime, timedelta, timezone

from .health import build_anomalies, pod_problem

KINDS = {"Pod": "pods", "Node": "nodes", "Deployment": "deployments", "ReplicaSet": "replicasets", "StatefulSet": "statefulsets", "DaemonSet": "daemonsets", "Job": "jobs", "CronJob": "cronjobs", "Service": "services", "PersistentVolumeClaim": "pvcs", "Cluster": "cnpg_clusters", "HelmRelease": "helmreleases", "Secret": "secrets"}
DIAGNOSES = {
    "CrashLoopBackOff": ("Redémarrages répétés après une erreur", "Un conteneur échoue au démarrage et Kubernetes espace ses nouvelles tentatives.", ["Consulter les logs et le dernier arrêt du conteneur.", "Vérifier sa configuration et ses dépendances."]),
    "ImagePullBackOff": ("Image impossible à télécharger", "Kubernetes n’arrive pas à récupérer l’image du conteneur.", ["Vérifier le nom et le tag de l’image.", "Vérifier l’accès au registre et les références imagePullSecrets."]),
    "OOMKilled": ("Conteneur arrêté faute de mémoire", "Le dernier arrêt est signalé OOMKilled par Kubernetes. Le pod peut avoir redémarré depuis.", ["Comparer consommation et limite mémoire dans la supervision.", "Examiner les logs et la pression mémoire de la machine."]),
    "Unschedulable": ("Pod sans machine d’exécution", "Kubernetes ne trouve pas de machine correspondant aux contraintes de ce pod. Cela ne signifie pas nécessairement un manque de capacité.", ["Lire les événements FailedScheduling.", "Comparer ressources demandées, affinités, taints et tolérances."]),
    "Pending": ("Pod en attente de démarrage", "Le pod attend encore une étape nécessaire à son exécution.", ["Consulter ses événements : placement, image ou montage d’un volume."]),
    "NotReady": ("Machine indisponible", "La machine ne se déclare pas prête à exécuter normalement les applications.", ["Consulter ses conditions et événements.", "Vérifier connectivité, pression disque et mémoire."]),
    "NotReadyPod": ("Pod non prêt à recevoir des connexions", "Le pod fonctionne mais ne se déclare pas prêt, ou un de ses conteneurs n’est pas prêt.", ["Consulter les événements et les résultats des sondes de disponibilité.", "Vérifier ses dépendances et ses logs."]),
    "NoReadyEndpoints": ("Point d’accès sans destination prête", "Aucun endpoint prêt n’est déclaré pour ce service. Il peut ne pas être disponible pour ses clients.", ["Vérifier les pods et leurs sondes de disponibilité.", "Comparer le sélecteur du service aux labels des pods."]),
    "RecentRestart": ("Redémarrage observé récemment", "Le dernier arrêt d’un conteneur date de moins de 15 minutes. Le compteur de redémarrages est cumulatif, pas limité à cette période.", ["Lire le dernier motif d’arrêt et les logs.", "Vérifier si le problème se reproduit."]),
    "WorkloadNotReady": ("Application partiellement disponible", "Le nombre d’instances prêtes est inférieur au nombre demandé. Un déploiement en cours peut aussi expliquer cet état.", ["Vérifier l’état des pods et la version déployée.", "Consulter les événements avant de conclure à une panne."]),
    "VolumePending": ("Stockage pas encore disponible", "Le volume demandé n’est pas lié à un stockage utilisable.", ["Consulter les événements du volume et sa classe de stockage."]),
    "NodePressure": ("Machine sous pression", "Kubernetes signale une pression sur les ressources de cette machine.", ["Consulter les conditions de la machine et les métriques correspondantes."]),
}
DIAGNOSES["ErrImagePull"] = DIAGNOSES["ImagePullBackOff"]


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _time(*values):
    return next((value for value in values if _date(value)), None)


def build_events(res: dict) -> list[dict]:
    rows = []
    for event in res.get("events", []):
        meta, ref = event.get("metadata") or {}, event.get("involvedObject") or {}
        series = event.get("series") or {}
        rows.append({
            "id": meta.get("uid") or f'{meta.get("namespace", "")}/{meta.get("name", "")}',
            "timestamp": _time(series.get("lastObservedTime"), event.get("lastTimestamp"), event.get("eventTime"), event.get("firstTimestamp"), meta.get("creationTimestamp")),
            "firstTimestamp": _time(event.get("firstTimestamp"), event.get("eventTime"), meta.get("creationTimestamp")),
            "count": series.get("count") or event.get("count") or 1,
            "type": event.get("type") or "Normal", "reason": event.get("reason") or "Événement",
            "message": (event.get("message") or "")[:2000],
            "object": {"kind": KINDS.get(ref.get("kind"), ref.get("kind", "")), "namespace": "" if ref.get("kind") == "Node" else ref.get("namespace", meta.get("namespace", "")), "name": ref.get("name", ""), "uid": ref.get("uid")},
        })
    return sorted(rows, key=lambda e: _date(e["timestamp"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:200]


def build_incidents(res: dict, metrics: dict, status=None, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    objects = {(kind, o["metadata"].get("namespace", ""), o["metadata"]["name"]): o for kind in set(KINDS.values()) for o in res.get(kind, [])}
    events = build_events(res)
    groups = {"active": {}, "history": {}}

    def descriptor(kind, obj):
        meta = obj["metadata"]
        return {"kind": kind, "namespace": meta.get("namespace", ""), "name": meta["name"], "uid": meta.get("uid")}

    def add(kind, obj, reason, severity="warn", history=False, since=None, evidence=""):
        selected = descriptor(kind, obj)
        parent_kind, parent = kind, obj
        for _ in range(4):
            owner = next((r for r in parent["metadata"].get("ownerReferences", []) if r.get("controller")), None)
            collection = KINDS.get((owner or {}).get("kind"))
            ancestor = objects.get((collection, selected["namespace"], (owner or {}).get("name")))
            if not ancestor or owner.get("uid") and owner["uid"] != ancestor["metadata"].get("uid"):
                break
            parent_kind, parent = collection, ancestor
        root = descriptor(parent_kind, parent)
        group_id = f'{root["kind"]}/{root["namespace"]}/{root["name"]}'
        bucket = groups["history" if history else "active"]
        group = bucket.setdefault(group_id, {**root, "id": group_id, "severity": severity, "issues": []})
        if severity == "bad":
            group["severity"] = "bad"
        summary, explanation, checks = DIAGNOSES.get(reason, ("Exécution terminée en échec" if history else "Ressource à vérifier", "Kubernetes signale cet état. Les événements et conditions permettent de préciser sa cause.", ["Consulter les conditions, événements et logs disponibles."]))
        if not since:
            event_reason = "BackOff" if reason == "CrashLoopBackOff" else reason
            since = next((e["firstTimestamp"] for e in events if e["reason"] == event_reason and e["object"]["kind"] == kind and e["object"]["namespace"] == selected["namespace"] and e["object"]["name"] == selected["name"] and (not e["object"]["uid"] or e["object"]["uid"] == selected["uid"])), None)
        group["issues"].append({**selected, "reason": reason, "severity": severity, "summary": summary, "explanation": explanation, "checks": checks, "since": since, "evidence": evidence or reason})

    # Reuse existing health checks, while terminal pods belong to execution history.
    for anomaly in build_anomalies(res, metrics):
        kind = KINDS[anomaly["kind"]]
        obj = objects[(kind, anomaly["namespace"], anomaly["name"])]
        if kind == "pods" and obj["metadata"].get("deletionTimestamp"):
            continue
        reason = anomaly["reason"]
        if kind in ("deployments", "statefulsets", "daemonsets", "cnpg_clusters"):
            reason = "WorkloadNotReady"
        elif kind == "pvcs":
            reason = "VolumePending"
        add(kind, obj, reason, anomaly["severity"], history=kind == "pods" and (obj.get("status") or {}).get("phase") == "Failed", evidence=anomaly["reason"])
    for pod in res.get("pods", []):
        st = pod.get("status") or {}
        if pod["metadata"].get("deletionTimestamp") or st.get("phase") in ("Failed", "Succeeded"):
            continue
        conditions = st.get("conditions") or []
        containers = (st.get("containerStatuses") or []) + (st.get("initContainerStatuses") or [])
        if not pod_problem(pod) and st.get("phase") == "Pending":
            scheduled = next((c for c in conditions if c.get("type") == "PodScheduled" and c.get("status") == "False"), {})
            add("pods", pod, "Unschedulable" if scheduled else "Pending", since=_time(scheduled.get("lastTransitionTime")))
        elif not pod_problem(pod) and any(c.get("type") == "Ready" and c.get("status") == "False" for c in conditions):
            add("pods", pod, "NotReadyPod")
        for container in containers:
            previous = (container.get("lastState") or {}).get("terminated") or {}
            finished = _date(previous.get("finishedAt"))
            if finished and timedelta(0) <= now - finished <= timedelta(minutes=15) and container.get("restartCount", 0):
                reason = "OOMKilled" if previous.get("reason") == "OOMKilled" else "RecentRestart"
                add("pods", pod, reason, since=previous["finishedAt"], evidence=f'{container.get("name", "conteneur")} · {container["restartCount"]} redémarrages cumulés · dernier arrêt : {previous.get("reason", "inconnu")}')
    for node in res.get("nodes", []):
        for condition in (node.get("status") or {}).get("conditions") or []:
            if condition.get("type") in ("MemoryPressure", "DiskPressure", "PIDPressure") and condition.get("status") == "True":
                add("nodes", node, "NodePressure", since=_time(condition.get("lastTransitionTime")), evidence=condition["type"])
    if "endpointslices" in res and (status is None or all(status.get(k) == "ok" for k in ("services", "endpointslices"))):
        ready_services = {(s["metadata"].get("namespace", ""), (s["metadata"].get("labels") or {}).get("kubernetes.io/service-name")) for s in res["endpointslices"] if any((e.get("conditions") or {}).get("ready") is not False for e in s.get("endpoints") or [])}
        for service in res.get("services", []):
            meta, spec = service["metadata"], service.get("spec") or {}
            if spec.get("selector") and spec.get("type") != "ExternalName" and (meta.get("namespace", ""), meta["name"]) not in ready_services:
                add("services", service, "NoReadyEndpoints")
    for job in res.get("jobs", []):
        failed = next((c for c in (job.get("status") or {}).get("conditions") or [] if c.get("type") == "Failed" and c.get("status") == "True"), None)
        if failed:
            add("jobs", job, failed.get("reason") or "Failed", history=True, since=_time(failed.get("lastTransitionTime")))
    return {key: sorted(bucket.values(), key=lambda g: (g["severity"] != "bad", g["namespace"], g["name"])) for key, bucket in groups.items()}
