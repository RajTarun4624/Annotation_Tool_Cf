FROM nginx:1.27-alpine

# Plain HTML + JS frontend — no build step. nginx serves the static files and
# proxies /api/ and /health to the backend service (see nginx.conf).
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY . /usr/share/nginx/html

EXPOSE 80
