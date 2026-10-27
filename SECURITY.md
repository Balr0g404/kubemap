# Security policy

Kubemap is a local Kubernetes client. Only the latest published version is supported while the project is in preview.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/Balr0g404/kubemap/security/advisories/new).

Include the affected version, operating system, enabled command-line options, steps to reproduce and expected impact. Use a minimal example with dummy credentials and resources.

Do not post exploit details, kubeconfigs, tokens, certificates, logs containing credentials or customer information in a public issue. If the private reporting form is unavailable, wait for the maintainer to enable it rather than opening a public vulnerability report. GitHub account security and access issues belong with GitHub Support.

## Local security model

The server listens on `127.0.0.1` and is intended for one local user. Do not expose it through a reverse proxy or public tunnel. Kubernetes permissions come from your kubeconfig; use a dedicated account with the least permissions required.

Collection is read-only. Writes, terminals, secret values, local port forwarding and local authentication plugins each require their own explicit launch option. Imported kubeconfigs cannot execute authentication plugins. A trusted local plugin runs with your operating-system user permissions.

Connection credentials stay in server memory. Closing the application clears them. Logs, events, annotations and custom fields can contain sensitive information even when standard container fields have been redacted. Processes and users on the same computer may access local forwarded ports.
