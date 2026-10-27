from pathlib import Path

import yaml

DEFAULT = Path(__file__).with_name("layers.yaml")


def load_layers(path=None) -> list[dict]:
    data = yaml.safe_load(Path(path or DEFAULT).read_text()) or {}
    return [{"name": layer["name"], "namespaces": list(layer.get("namespaces") or [])} for layer in data.get("layers", [])]
