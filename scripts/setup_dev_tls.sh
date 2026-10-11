#!/usr/bin/env bash
set -euo pipefail
# Generate a short-lived self-signed development certificate. Browsers/phones must
# explicitly trust it; for production use a real reverse proxy/CA certificate.
HOST="${1:-localhost}"
OUT="${2:-data/tls}"
DAYS="${GUARDLENS_TLS_DAYS:-30}"
if ! command -v openssl >/dev/null; then echo "openssl is required" >&2; exit 2; fi
mkdir -p "$OUT"; chmod 700 "$OUT"
if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then SAN="IP:${HOST},DNS:localhost,IP:127.0.0.1"; else SAN="DNS:${HOST},DNS:localhost,IP:127.0.0.1"; fi
openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days "$DAYS" \
  -keyout "$OUT/key.pem" -out "$OUT/cert.pem" -subj "/CN=$HOST" \
  -addext "subjectAltName=$SAN" >/dev/null 2>&1
chmod 600 "$OUT/key.pem"; chmod 644 "$OUT/cert.pem"
printf 'Generated development TLS files:\n  %s/cert.pem\n  %s/key.pem\n\nRun:\n' "$OUT" "$OUT"
printf 'GUARDLENS_SSL_CERTFILE=%q GUARDLENS_SSL_KEYFILE=%q ./run.sh\n' "$OUT/cert.pem" "$OUT/key.pem"
printf '\nTrust cert.pem on each test device before browser camera use. Do not use this self-signed certificate for production.\n'
