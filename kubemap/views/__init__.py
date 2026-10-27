from .exposure import build_exposure
from .health import build_anomalies, build_map, build_overview
from .jobs import build_jobs
from .storage import build_storage
from .incidents import build_events, build_incidents


def build_views(res: dict, metrics: dict, layers: list[dict], status=None) -> dict:
    exposure = build_exposure(res)
    return {
        "overview": build_overview(res, metrics),
        "anomalies": build_anomalies(res, metrics),
        "incidents": build_incidents(res, metrics, status=status),
        "events": build_events(res),
        "map": build_map(res, exposure, layers),
        "exposure": exposure,
        "jobs": build_jobs(res.get("jobs", []), res.get("cronjobs", [])),
        "storage": build_storage(res),
    }
