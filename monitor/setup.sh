#!/bin/bash

set -e

if [ "$RUNNER_OS" != "Linux" ]; then
  echo "Only Linux is supported"
  exit 1
fi

# build the filter regex for mitmproxy --allow-hosts
filter='\b('
first=true
IFS=',' read -ra args <<< "$@"
for arg in "${args[@]}"; do
  if [ "$first" = true ] ; then
    first=false
  else
    filter+='|'
  fi
  filter+=${arg//./\\.}
done
filter+=')(:\d+)?|$'

# create mitmproxyuser, otherwise proxy won't intercept local traffic from the same user
sudo useradd --create-home mitmproxyuser
sudo passwd -d mitmproxyuser

# install uv and mitmproxy as mitmproxyuser
sudo -u mitmproxyuser -H bash -e -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u mitmproxyuser -H bash -e -c 'cd ~ && ~/.local/bin/uv venv && ~/.local/bin/uv pip install mitmproxy==11.1.3 requests==2.32.3'

sudo cp mitm_plugin.py /home/mitmproxyuser/mitm_plugin.py
sudo -u mitmproxyuser -H bash -e -c "cd /home/mitmproxyuser && \
    /home/mitmproxyuser/.venv/bin/mitmdump \
        --mode transparent \
        --showhost \
        --allow-hosts '$filter' \
        -q \
        -s /home/mitmproxyuser/mitm_plugin.py \
        --set output='/home/mitmproxyuser/out.txt' \
        --set token='$INPUT_TOKEN' \
        --set hosts=$@ \
        --set debug='$RUNNER_DEBUG' \
        --set ACTIONS_ID_TOKEN_REQUEST_URL='$ACTIONS_ID_TOKEN_REQUEST_URL' \
        --set ACTIONS_ID_TOKEN_REQUEST_TOKEN='$ACTIONS_ID_TOKEN_REQUEST_TOKEN' \
        --set GITHUB_REPOSITORY_ID='$GITHUB_REPOSITORY_ID' \
        --set GITHUB_REPOSITORY='$GITHUB_REPOSITORY' \
        --set GITHUB_API_URL='$GITHUB_API_URL' \
        &"

# wait for mitmdump to start and generate CA certificate
counter=0
while [ ! -f /home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem ]
do
  echo "waiting for mitmdump to generate the certificate..."
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
# set environment variable for NodeJS to use the certificate
echo "NODE_EXTRA_CA_CERTS=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
# set environment variable for the Python requests library to use the certificate
echo "REQUESTS_CA_BUNDLE=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
# set environment variable for the Elixir Hex package manager to use the certificate
echo "HEX_CACERTS_PATH=/home/mitmproxyuser/.mitmproxy/mitmproxy-ca-cert.pem" >> $GITHUB_ENV
# set environment variable for AWS tools
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
