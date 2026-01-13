#!/bin/bash

set -e

# Create mitmproxyuser - proxy won't intercept local traffic from same user
sudo useradd mitmproxyuser
sudo mkdir -p /home/mitmproxyuser/.local/bin
sudo chown -R mitmproxyuser:mitmproxyuser /home/mitmproxyuser

# Install uv (UV_UNMANAGED_INSTALL skips receipt file for CI)
sudo -u mitmproxyuser -H bash -e -c 'curl -LsSf https://astral.sh/uv/install.sh | UV_UNMANAGED_INSTALL=/home/mitmproxyuser/.local/bin sh'

# Copy proxy script and config
sudo cp proxy.py config.json /home/mitmproxyuser/
sudo chown mitmproxyuser:mitmproxyuser /home/mitmproxyuser/config.json
sudo chmod 600 /home/mitmproxyuser/config.json

# Start proxy in background (--python 3.12 ensures compatible version)
sudo -i -u mitmproxyuser /home/mitmproxyuser/.local/bin/uv run --python 3.12 /home/mitmproxyuser/proxy.py &

# Setup iptables while proxy starts (doesn't need cert)
sudo sysctl -w net.ipv4.ip_forward=1
sudo sysctl -w net.ipv6.conf.all.forwarding=1
sudo sysctl -w net.ipv4.conf.all.send_redirects=0
sudo iptables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 80 -j REDIRECT --to-port 8080
sudo iptables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 443 -j REDIRECT --to-port 8080
sudo ip6tables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 80 -j REDIRECT --to-port 8080
sudo ip6tables -t nat -A OUTPUT -p tcp -m owner ! --uid-owner mitmproxyuser --dport 443 -j REDIRECT --to-port 8080
sudo mkdir -p /usr/local/share/ca-certificates/extra

# Wait for proxy to generate CA certificate
counter=0
while [ ! -f /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]; do
  sleep 0.25
  counter=$((counter+1))
  if [ $counter -gt 40 ]; then
    echo "Timeout waiting for certificate"
    exit 1
  fi
done

# Install mitmproxy certificate as system CA
sudo openssl x509 -in /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem -inform PEM -out ~/mitmproxy-ca-cert.crt
sudo cp ~/mitmproxy-ca-cert.crt /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt
sudo dpkg-reconfigure -p critical ca-certificates
sudo update-ca-certificates

# Set CA env vars for tools that don't use system store
echo "NODE_EXTRA_CA_CERTS=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
echo "REQUESTS_CA_BUNDLE=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
echo "HEX_CACERTS_PATH=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
echo "AWS_CA_BUNDLE=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV

echo "--all done--"
