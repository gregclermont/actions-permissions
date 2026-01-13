#!/usr/bin/env python3
# /// script
# dependencies = ["mitmproxy==11.1.3"]
# ///
"""
GitHub Actions API call monitor using mitmproxy.

Runs a transparent proxy that logs GitHub API calls made with the workflow token.
"""

import asyncio
import base64
import json
from urllib.parse import urlsplit

from mitmproxy import options, http
from mitmproxy.tools.dump import DumpMaster


class GitHubAPIMonitor:
    """mitmproxy addon that logs GitHub API calls."""

    def __init__(self, token, output_file, id_token=None, debug=False):
        self.token = token
        self.output_file = output_file
        self.id_token = id_token
        self.debug = debug
        self.debug_file = output_file.replace('.txt', '-debug.txt')

        # Create empty output file
        open(output_file, 'a+').close()
        if debug:
            open(self.debug_file, 'a+').close()

    def _contains_token(self, header, token):
        if header.upper().strip().startswith('BASIC '):
            try:
                return token in base64.b64decode(header[6:]).decode()
            except Exception:
                return False
        return token in header

    def _write_request(self, method, host, path, query, user_agent=None, oidc=False, headers=None):
        record = {'method': method, 'host': host, 'path': path}
        if query:
            record['query'] = query
        if user_agent:
            record['user_agent'] = user_agent
        if oidc:
            record['oidc'] = True

        with open(self.output_file, 'a+') as f:
            f.write(json.dumps(record) + '\n')

        if self.debug and headers:
            debug_record = {**record, 'headers': headers}
            with open(self.debug_file, 'a+') as f:
                f.write(json.dumps(debug_record) + '\n')

    def requestheaders(self, flow: http.HTTPFlow):
        try:
            # allow_hosts ensures we only see requests to monitored hosts
            url_parts = urlsplit(flow.request.url)

            auth = flow.request.headers.get('Authorization', '')
            if not auth:
                return

            # Collect headers for debug logging (redact auth)
            headers = None
            if self.debug:
                headers = {k: ('REDACTED' if k.lower() == 'authorization' else v)
                          for k, v in flow.request.headers.items()}
                # Add flow.request.* properties to understand HTTP/1.1 vs HTTP/2
                headers['_http_version'] = flow.request.http_version
                headers['_host'] = flow.request.host
                headers['_pretty_host'] = flow.request.pretty_host
                headers['_host_header'] = flow.request.host_header
                headers['_authority'] = getattr(flow.request, 'authority', None)

            user_agent = flow.request.headers.get('User-Agent')

            # Check for GitHub token
            if self._contains_token(auth, self.token):
                self._write_request(flow.request.method, flow.request.pretty_host, url_parts.path, url_parts.query, user_agent=user_agent, headers=headers)

            # Check for OIDC token request (uses ACTIONS_ID_TOKEN_REQUEST_TOKEN)
            elif self.id_token and self._contains_token(auth, self.id_token):
                self._write_request(flow.request.method, flow.request.pretty_host, url_parts.path, url_parts.query, user_agent=user_agent, oidc=True, headers=headers)

        except Exception:
            import traceback
            traceback.print_exc()
            with open('error.log', 'a+') as f:
                f.write(traceback.format_exc() + '\n')


async def run_proxy(hosts, token, output_file, id_token=None, debug=False):
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
        id_token=id_token,
        debug=debug,
    )
    master.addons.add(addon)

    try:
        await master.run()
    except KeyboardInterrupt:
        master.shutdown()


def main():
    with open('/home/mitmproxyuser/config.json') as f:
        config = json.load(f)

    asyncio.run(run_proxy(
        hosts=config['hosts'],
        token=config['token'],
        output_file='/home/mitmproxyuser/out.txt',
        id_token=config.get('idToken'),
        debug=config.get('debug', False),
    ))


if __name__ == '__main__':
    main()
