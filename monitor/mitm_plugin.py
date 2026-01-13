import base64
import json
import sys
from urllib.parse import urlsplit
from mitmproxy import ctx


class GHActionsProxy:
    def __init__(self):
        self.ip_map = {}
        self.dns_map = {}

    def add_to_maps(self, dns):
        import socket
        ip = socket.gethostbyname(dns)
        self.ip_map[ip] = dns
        self.dns_map[dns] = ip

    def rebuild_cache(self):
        for host in ctx.options.hosts.split(','):
            self.add_to_maps(host.strip())

    def load(self, loader):
        loader.add_option(name='output', typespec=str, default='', help='Output file path')
        loader.add_option(name='token', typespec=str, default='', help='GitHub token')
        loader.add_option(name='debug', typespec=str, default='', help='Enable debug logging')
        loader.add_option(name='hosts', typespec=str, default='', help='Comma delimited list of hosts to monitor')
        loader.add_option(name='ACTIONS_ID_TOKEN_REQUEST_URL', typespec=str, default='', help='OIDC token request URL')
        loader.add_option(name='ACTIONS_ID_TOKEN_REQUEST_TOKEN', typespec=str, default='', help='OIDC token request token')

    def log_debug(self, msg):
        if ctx.options.debug:
            with open('debug.log', 'a+') as f:
                f.write('%s\n' % msg)

    def configure(self, updates):
        self.log_debug('Proxy debug messages enabled')
        with open(ctx.options.output, 'a+') as f:
            pass  # create empty file

        if not ctx.options.hosts:
            print('error: Hosts argument is empty')
            sys.exit(1)
        if not ctx.options.token:
            print('error: GitHub token is empty')
            sys.exit(1)

        self.rebuild_cache()
        self.log_debug(str(self.ip_map))

        self.id_token_url = None
        self.id_token = None
        if ctx.options.ACTIONS_ID_TOKEN_REQUEST_URL:
            self.id_token_url = urlsplit(ctx.options.ACTIONS_ID_TOKEN_REQUEST_URL)
        if ctx.options.ACTIONS_ID_TOKEN_REQUEST_TOKEN:
            self.id_token = ctx.options.ACTIONS_ID_TOKEN_REQUEST_TOKEN

    def contains_token(self, header, token):
        if header.upper().strip().startswith('BASIC '):
            return token in base64.b64decode(header[6:]).decode()
        return token in header

    def get_hostname(self, flow):
        url_parts = urlsplit(flow.request.url)
        hostname = url_parts.hostname.lower()

        # Check for Host header
        for k, v in flow.request.headers.items():
            if k.upper().strip() == 'HOST':
                return v.lower().strip(), url_parts

        # Resolve IP to hostname if needed
        if hostname not in self.dns_map and hostname not in self.ip_map:
            self.rebuild_cache()
        if hostname in self.ip_map:
            hostname = self.ip_map[hostname]

        return hostname, url_parts

    def requestheaders(self, flow):
        try:
            hostname, url_parts = self.get_hostname(flow)
            self.log_debug('%s %s' % (flow.request.method, flow.request.url))

            for k, v in flow.request.headers.items():
                if not k.upper().strip().startswith('AUTHORIZATION'):
                    continue

                self.log_debug('Request contains authorization header')

                # Check for GitHub token
                if self.contains_token(v, ctx.options.token):
                    if hostname in self.ip_map or hostname in self.dns_map:
                        self.write_request(flow.request.method, hostname, url_parts.path, url_parts.query)

                # Check for OIDC token
                elif self.id_token and self.contains_token(v, self.id_token):
                    if self.id_token_url and flow.request.method == 'GET':
                        if hostname == self.id_token_url.hostname.lower() and url_parts.path.lower() == self.id_token_url.path.lower():
                            self.write_request(flow.request.method, hostname, url_parts.path, url_parts.query, oidc=True)

        except Exception as e:
            import traceback
            print(traceback.format_exc())
            with open('error.log', 'a+') as f:
                f.write(traceback.format_exc() + '\n')

    def write_request(self, method, host, path, query, oidc=False):
        with open(ctx.options.output, 'a+') as f:
            record = {'method': method, 'host': host, 'path': path}
            if query:
                record['query'] = query
            if oidc:
                record['oidc'] = True
            f.write(json.dumps(record) + '\n')


addons = [GHActionsProxy()]
