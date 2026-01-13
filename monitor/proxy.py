#!/usr/bin/env python3
# /// script
# dependencies = ["mitmproxy==11.1.3"]
# ///
"""
GitHub Actions API call monitor using mitmproxy.

Runs a transparent proxy that logs GitHub API calls made with the workflow token.
"""

import argparse
import asyncio
import base64
import json
import sys
from urllib.parse import urlsplit

from mitmproxy import options, http
from mitmproxy.tools.dump import DumpMaster


class GitHubAPIMonitor:
    """mitmproxy addon that logs GitHub API calls."""

    def __init__(self, token, output_file, id_token_url=None, id_token=None):
        self.token = token
        self.output_file = output_file
        self.id_token_url = urlsplit(id_token_url) if id_token_url else None
        self.id_token = id_token

        # Create empty output file
        open(output_file, 'a+').close()

    def _contains_token(self, header, token):
        if header.upper().strip().startswith('BASIC '):
            try:
                return token in base64.b64decode(header[6:]).decode()
            except Exception:
                return False
        return token in header

    def _write_request(self, method, host, path, query, oidc=False):
        record = {'method': method, 'host': host, 'path': path}
        if query:
            record['query'] = query
        if oidc:
            record['oidc'] = True

        with open(self.output_file, 'a+') as f:
            f.write(json.dumps(record) + '\n')

    def requestheaders(self, flow: http.HTTPFlow):
        try:
            # mitmproxy provides host/path with showhost=True, and allow_hosts
            # ensures we only see requests to monitored hosts
            host = flow.request.host.lower()
            url_parts = urlsplit(flow.request.url)

            auth = flow.request.headers.get('Authorization', '')
            if not auth:
                return

            # Check for GitHub token
            if self._contains_token(auth, self.token):
                self._write_request(flow.request.method, host, url_parts.path, url_parts.query)

            # Check for OIDC token
            elif self.id_token and self._contains_token(auth, self.id_token):
                if self.id_token_url and flow.request.method == 'GET':
                    if (host == self.id_token_url.hostname.lower() and
                        url_parts.path.lower() == self.id_token_url.path.lower()):
                        self._write_request(flow.request.method, host, url_parts.path, url_parts.query, oidc=True)

        except Exception:
            import traceback
            traceback.print_exc()
            with open('error.log', 'a+') as f:
                f.write(traceback.format_exc() + '\n')


async def run_proxy(hosts, token, output_file, id_token_url=None, id_token=None):
    """Run mitmproxy with the GitHub API monitor addon."""

    # Build allow_hosts regex from host list
    escaped = [h.replace('.', r'\.') for h in hosts]
    allow_hosts_regex = r'\b(' + '|'.join(escaped) + r')(:\d+)?$'

    opts = options.Options(
        mode=['transparent'],
        showhost=True,
        allow_hosts=[allow_hosts_regex],
        listen_port=8080,
    )

    master = DumpMaster(opts)

    addon = GitHubAPIMonitor(
        token=token,
        output_file=output_file,
        id_token_url=id_token_url,
        id_token=id_token,
    )
    master.addons.add(addon)

    try:
        await master.run()
    except KeyboardInterrupt:
        master.shutdown()


def main():
    parser = argparse.ArgumentParser(description='GitHub API call monitor')
    parser.add_argument('--hosts', required=True, help='Comma-separated hosts to monitor')
    parser.add_argument('--token', required=True, help='GitHub token to detect')
    parser.add_argument('--output', default='/home/mitmproxyuser/out.txt', help='Output file')
    parser.add_argument('--id-token-url', help='OIDC token request URL')
    parser.add_argument('--id-token', help='OIDC token')
    args = parser.parse_args()

    hosts = [h.strip() for h in args.hosts.split(',')]

    asyncio.run(run_proxy(
        hosts=hosts,
        token=args.token,
        output_file=args.output,
        id_token_url=args.id_token_url,
        id_token=args.id_token,
    ))


if __name__ == '__main__':
    main()
