#!/bin/bash

set -e

echo "$(date +%T.%3N) setup.sh started"

# create mitmproxyuser, otherwise proxy won't intercept local traffic from the same user
echo "$(date +%T.%3N) Creating user..."
sudo useradd mitmproxyuser
sudo mkdir -p /home/mitmproxyuser/.local/bin
sudo chown -R mitmproxyuser:mitmproxyuser /home/mitmproxyuser
echo "$(date +%T.%3N) User created"

# install uv as mitmproxyuser (UV_UNMANAGED_INSTALL skips receipt file for CI)
echo "$(date +%T.%3N) Installing uv..."
sudo -u mitmproxyuser -H bash -e -c 'curl -LsSf https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL=/home/mitmproxyuser/.local/bin sh'
echo "$(date +%T.%3N) uv installed"

# copy proxy script
sudo cp proxy.py /home/mitmproxyuser/proxy.py

echo "$(date +%T.%3N) Starting proxy..."
# start proxy in background
# Arguments: hosts token [id_token_url] [id_token] [debug]
proxy_args="--hosts $1 --token $2"
if [ -n "$3" ]; then
  proxy_args="$proxy_args --id-token-url $3"
fi
if [ -n "$4" ]; then
  proxy_args="$proxy_args --id-token $4"
fi
if [ -n "$5" ]; then
  proxy_args="$proxy_args --debug"
fi
sudo -i -u mitmproxyuser /home/mitmproxyuser/.local/bin/uv run /home/mitmproxyuser/proxy.py $proxy_args &

# wait for proxy to start and generate CA certificate
counter=0
while [ ! -f /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]
do
  echo "$(date +%T.%3N) waiting for proxy to generate the certificate..."
  sleep 1
  counter=$((counter+1))
  if [ $counter -gt 10 ]; then
    exit 1
  fi
done
echo "$(date +%T.%3N) Certificate ready"

# install mitmproxy certificate as CA
sudo mkdir -p /usr/local/share/ca-certificates/extra
sudo openssl x509 -in /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem -inform PEM -out ~/mitmproxy-ca-cert.crt
sudo cp ~/mitmproxy-ca-cert.crt /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt
sudo dpkg-reconfigure -p critical ca-certificates
sudo update-ca-certificates
echo "NODE_EXTRA_CA_CERTS=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
echo "REQUESTS_CA_BUNDLE=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
echo "HEX_CACERTS_PATH=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
echo "AWS_CA_BUNDLE=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV

# setup global redirection
sudo sysctl -w net.ipv4.ip_forward=1
sudo sysctl -w net.ipv6.conf.all.forwarding=1
sudo sysctl -w net.ipv4.conf.all.send_redirects=0
sudo iptables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 80 -j REDIRECT --to-port 8080
sudo iptables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 443 -j REDIRECT --to-port 8080
sudo ip6tables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 80 -j REDIRECT --to-port 8080
sudo ip6tables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 443 -j REDIRECT --to-port 8080

echo "--all done--"
