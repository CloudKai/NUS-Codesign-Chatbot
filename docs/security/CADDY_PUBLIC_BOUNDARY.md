# Caddy public boundary checks

Caddy terminates HTTPS and exposes only Streamlit plus a short allow-list of
auth/health FastAPI routes. Private application APIs must return edge `404`.

## Public routes (expect proxied responses)

Replace the host with the production domain when verifying live.

```bash
# Lightweight process probe (public)
curl -sS -o /dev/null -w "%{http_code}\n" https://cde2300chatbot.duckdns.org/api/v1/health

# Auth entrypoints should not return Caddy's generic Not Found body
curl -sS -o /dev/null -w "%{http_code}\n" https://cde2300chatbot.duckdns.org/api/v1/auth/me
curl -sS -o /dev/null -w "%{http_code}\n" \
  -X POST https://cde2300chatbot.duckdns.org/api/v1/auth/login

# Streamlit UI
curl -sS -o /dev/null -w "%{http_code}\n" https://cde2300chatbot.duckdns.org/
```

## Private routes (expect HTTP 404 from Caddy)

```bash
for path in \
  /api/v1/ready \
  /api/v1/threads \
  /api/v1/coach/turn \
  /api/v1/preferences
do
  code=$(curl -sS -o /tmp/caddy-body.txt -w "%{http_code}" \
    "https://cde2300chatbot.duckdns.org${path}")
  body=$(cat /tmp/caddy-body.txt)
  echo "$path -> $code ($body)"
  test "$code" = "404"
done
```

Internal readiness remains reachable only on the Docker network, for example
from the app healthcheck against `http://127.0.0.1:8000/api/v1/ready`.

## Security headers

After TLS is live, confirm response headers include:

- `Strict-Transport-Security`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` (camera/microphone/geolocation disabled)

Do **not** enable a Content-Security-Policy until Streamlit has been verified
under that policy; a blind CSP commonly breaks Streamlit websockets and assets.
