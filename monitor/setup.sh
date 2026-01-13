#!/bin/bash

set -e

# create mitmproxyuser, otherwise proxy won't intercept local traffic from the same user
sudo useradd --create-home mitmproxyuser
sudo passwd -d mitmproxyuser

# install uv as mitmproxyuser
sudo -u mitmproxyuser -H bash -e -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

# copy proxy script
sudo cp proxy.py /home/mitmproxyuser/proxy.py

# start proxy in background (reads config from environment variables)
sudo -u mitmproxyuser bash -e -c "
  export HOME=/home/mitmproxyuser
  export INPUT_TOKEN='$INPUT_TOKEN'
  export GITHUB_SERVER_URL='$GITHUB_SERVER_URL'
  export GITHUB_API_URL='$GITHUB_API_URL'
  export ACTIONS_ID_TOKEN_REQUEST_URL='$ACTIONS_ID_TOKEN_REQUEST_URL'
  export ACTIONS_ID_TOKEN_REQUEST_TOKEN='$ACTIONS_ID_TOKEN_REQUEST_TOKEN'
  cd ~ && ~/.local/bin/uv run proxy.py &
"

# wait for proxy to start and generate CA certificate
counter=0
while [ ! -f /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]
do
  echo "waiting for proxy to generate the certificate..."
  sleep 1
  counter=$((counter+1))
  if [ $counter -gt 10 ]; then
    exit 1
  fi
done

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
