import argparse
import logging
from pathlib import Path

import uvicorn

from .api import create_app
from .kube import KubeClient
from .kubeconfig import load, local_document
from .layers import load_layers
from .store import Store

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="kubemap", description="Cartographie en lecture seule du cluster")
    parser.add_argument("--context", help="contexte du kubeconfig (défaut : contexte courant)")
    parser.add_argument("--kubeconfig", help="fichier à charger au démarrage (sinon : import dans l’interface)")
    parser.add_argument("--layers", help="fichier de couches (défaut : kubemap/layers.yaml)")
    parser.add_argument("--allow-exec", action="store_true", help="autorise l’ouverture d’un terminal (bash) dans les conteneurs : lève la lecture seule")
    parser.add_argument("--allow-secrets", action="store_true", help="autorise l’affichage des valeurs d’un secret (après confirmation) : lève la lecture seule")
    parser.add_argument("--allow-exec-auth", action="store_true", help="autorise les plugins ExecCredential du kubeconfig local explicitement choisi")
    parser.add_argument("--allow-write", action="store_true", help="autorise les actions ciblées de gestion après confirmation")
    parser.add_argument("--allow-portforward", action="store_true", help="autorise les tunnels TCP locaux vers les pods")
    parser.add_argument("--desktop", action="store_true", help="ouvre Kubemap dans une fenêtre desktop (dépendances desktop requises)")
    parser.add_argument("--port", type=int, help="port local (web : 8765 ; desktop : port libre)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.context and not args.kubeconfig:
        parser.error("--context nécessite --kubeconfig ; sinon, choisissez le contexte dans l’interface")
    if args.allow_exec_auth and not args.kubeconfig:
        parser.error("--allow-exec-auth nécessite un --kubeconfig local explicitement choisi")
    cfg = load(args.kubeconfig, context=args.context, allow_exec_auth=args.allow_exec_auth) if args.kubeconfig else None
    layers = load_layers(args.layers)
    store = Store(KubeClient(cfg.server, cfg.ssl_context, cfg.token, credentials=cfg.credentials) if cfg else None, cluster_name=cfg.cluster_name if cfg else "", context_name=cfg.context_name if cfg else "", layers=layers)
    if args.kubeconfig:
        store.connection_document = local_document(args.kubeconfig)
        store.connection_trusted = True
    store.allow_exec_auth = args.allow_exec_auth
    store.allow_write = args.allow_write
    store.allow_portforward = args.allow_portforward
    store.allow_exec = args.allow_exec
    store.allow_secrets = args.allow_secrets
    app = create_app(store, DIST)
    if args.desktop:
        from .desktop import run
        try:
            run(app, DIST, port=args.port if args.port is not None else 0)
        except (ImportError, OSError, RuntimeError) as exc:
            parser.exit(1, f"Kubemap desktop : {exc}\n")
    else:
        uvicorn.run(app, host="127.0.0.1", port=args.port if args.port is not None else 8765, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
