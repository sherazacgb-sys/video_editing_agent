#!/bin/bash
# One-time bootstrap for the nginx + certbot setup in docker-compose.prod.yml.
# Run this once on the EC2 host, from the repo root, before the first `docker
# compose -f docker-compose.prod.yml up -d`. Not needed again after that — the
# `certbot` service in docker-compose.prod.yml handles renewal on its own.
#
# Why this exists at all: nginx's HTTPS server block (nginx/conf.d/app.conf)
# references cert files that don't exist until Let's Encrypt issues them, but
# Let's Encrypt can't issue them until nginx is up and serving the ACME challenge
# path on port 80 — a chicken-and-egg problem. This script breaks the cycle by
# starting nginx with a throwaway self-signed cert first, then swapping in the
# real one.

set -e

domain="sherazlabs.co.uk"
email="" # fill in an admin email before running — Let's Encrypt uses it for expiry/security notices
data_path="./certbot"
rsa_key_size=4096
staging=0 # set to 1 while testing to avoid hitting Let's Encrypt's real-cert rate limits

if [ -d "$data_path/conf/live/$domain" ]; then
  read -p "Existing certificate data found for $domain. Continue and replace it? (y/N) " decision
  if [ "$decision" != "y" ]; then
    exit
  fi
fi

if [ ! -e "$data_path/conf/options-ssl-nginx.conf" ] || [ ! -e "$data_path/conf/ssl-dhparams.pem" ]; then
  echo "Downloading recommended TLS parameters..."
  mkdir -p "$data_path/conf"
  # Certbot's own recommended nginx TLS config (protocols/ciphers) and DH params —
  # referenced by nginx/conf.d/app.conf but not vendored into this repo.
  curl -s "https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf" > "$data_path/conf/options-ssl-nginx.conf"
  curl -s "https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem" > "$data_path/conf/ssl-dhparams.pem"
fi

echo "Creating a dummy certificate so nginx can start..."
path="/etc/letsencrypt/live/$domain"
mkdir -p "$data_path/conf/live/$domain"
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1 \
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "Starting nginx with the dummy certificate..."
docker compose -f docker-compose.prod.yml up -d nginx

echo "Deleting the dummy certificate..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$domain && \
  rm -Rf /etc/letsencrypt/archive/$domain && \
  rm -Rf /etc/letsencrypt/renewal/$domain.conf" certbot

echo "Requesting the real Let's Encrypt certificate..."
domain_args="-d $domain"
email_arg="--email $email"
if [ -z "$email" ]; then email_arg="--register-unsafely-without-email"; fi
staging_arg=""
if [ "$staging" != "0" ]; then staging_arg="--staging"; fi

docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    $domain_args \
    --rsa-key-size $rsa_key_size \
    --agree-tos \
    --force-renewal" certbot

echo "Reloading nginx with the real certificate..."
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
