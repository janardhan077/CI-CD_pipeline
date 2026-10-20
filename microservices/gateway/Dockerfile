FROM nginx:1.27-alpine

COPY gateway/nginx.conf /etc/nginx/nginx.conf
COPY gateway/static /usr/share/nginx/html/static
COPY gateway/static/index.html /usr/share/nginx/html/index.html

EXPOSE 8000
