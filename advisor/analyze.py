#!/usr/bin/env python3
"""
Analyze GitHub API call logs and determine required permissions.

Input: JSON array of requests [{method, host, path, query?, oidc?}, ...]
Output: JSON object of permissions {permission: level, ...}

Environment variables:
  GITHUB_TOKEN - Token for API calls (disambiguation, public repo checks)
  GITHUB_REPOSITORY - Current repository (owner/repo format)
  GITHUB_API_URL - API URL (default: https://api.github.com)
"""

import json
import os
import sys
from urllib.parse import parse_qs

# Optional requests for disambiguation - gracefully degrade if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class PermissionAnalyzer:
    def __init__(self, token=None, repository=None, api_url=None):
        self.token = token
        self.repository = repository
        self.api_url = api_url or 'https://api.github.com'
        self.repo_cache = {}  # Cache for public repo checks
        self.pr_cache = {}    # Cache for issue/PR disambiguation

        # Special case mappings that don't follow the standard pattern
        self.special_cases = self._build_special_cases()

    def _build_special_cases(self):
        """Build mapping for endpoints that don't follow standard patterns."""
        cases = [
            # Contents endpoints
            ('GET', '/repos/{owner}/{repo}/codeowners/errors', 'contents', 'read'),
            ('PUT', '/repos/{owner}/{repo}/pulls/{n}/merge', 'contents', 'write'),
            ('PUT', '/repos/{owner}/{repo}/pulls/{n}/update-branch', 'contents', 'write'),
            ('POST', '/repos/{owner}/{repo}/comments/{n}/reactions', 'contents', 'write'),
            ('DELETE', '/repos/{owner}/{repo}/comments/{n}/reactions/{n}', 'contents', 'write'),
            ('GET', '/repos/{owner}/{repo}/branches', 'contents', 'read'),
            ('POST', '/repos/{owner}/{repo}/merge-upstream', 'contents', 'write'),
            ('POST', '/repos/{owner}/{repo}/merges', 'contents', 'write'),
            ('PATCH', '/repos/{owner}/{repo}/comments/{n}', 'contents', 'write'),
            ('DELETE', '/repos/{owner}/{repo}/comments/{n}', 'contents', 'write'),
            ('POST', '/repos/{owner}/{repo}/dispatches', 'contents', 'write'),

            # Issues endpoints (unambiguous)
            ('POST', '/repos/{owner}/{repo}/issues', 'issues', 'write'),
            ('GET', '/repos/{owner}/{repo}/labels', 'issues', 'read'),
            ('POST', '/repos/{owner}/{repo}/labels', 'issues', 'write'),
            ('GET', '/repos/{owner}/{repo}/labels/{n}', 'issues', 'read'),
            ('PATCH', '/repos/{owner}/{repo}/labels/{n}', 'issues', 'write'),
            ('DELETE', '/repos/{owner}/{repo}/labels/{n}', 'issues', 'write'),
            ('GET', '/repos/{owner}/{repo}/milestones', 'issues', 'read'),
            ('POST', '/repos/{owner}/{repo}/milestones', 'issues', 'write'),
            ('GET', '/repos/{owner}/{repo}/milestones/{n}', 'issues', 'read'),
            ('PATCH', '/repos/{owner}/{repo}/milestones/{n}', 'issues', 'write'),
            ('DELETE', '/repos/{owner}/{repo}/milestones/{n}', 'issues', 'write'),
            ('GET', '/repos/{owner}/{repo}/milestones/{n}/labels', 'issues', 'read'),

            # Ambiguous issues/pull-requests endpoints - return both
            ('GET', '/repos/{owner}/{repo}/issues', 'issues+pull-requests', 'read'),
            ('GET', '/repos/{owner}/{repo}/issues/comments', 'issues+pull-requests', 'read'),
            ('GET', '/repos/{owner}/{repo}/issues/events', 'issues+pull-requests', 'read'),
            ('GET', '/repos/{owner}/{repo}/assignees', 'issues+pull-requests', 'read'),
        ]

        # Build a lookup structure: (method, pattern_tuple) -> (permission, level)
        result = {}
        for method, path, perm, level in cases:
            # Convert path to a tuple of segments, using '*' for variables
            segments = tuple(
                '*' if s.startswith('{') else s
                for s in path.split('/')[1:]
            )
            result[(method, segments)] = (perm, level)

        return result

    def _match_special_case(self, method, path):
        """Check if path matches a special case pattern."""
        segments = tuple(path.split('/')[1:])
        # Try exact match first, then with wildcards
        for i in range(len(segments) + 1):
            # Generate pattern with wildcards for numeric segments
            pattern = tuple(
                '*' if (j >= len(segments) - i and s.isdigit()) or s.startswith('{')
                else s
                for j, s in enumerate(segments)
            )
            key = (method, pattern)
            if key in self.special_cases:
                return self.special_cases[key]
        return None

    def _is_same_repo(self, path_segments):
        """Check if the request targets the current repository."""
        if not self.repository:
            return True  # Can't filter, assume same repo

        if len(path_segments) >= 4 and path_segments[1] == 'repos':
            target = f"{path_segments[2]}/{path_segments[3]}"
            return target.lower() == self.repository.lower()
        elif len(path_segments) >= 3 and path_segments[1] == 'repositories':
            # Repository ID - can't easily compare, assume same repo
            return True
        return True

    def _is_public_repo(self, repo):
        """Check if a repository is public (caches results)."""
        if not HAS_REQUESTS or not self.token:
            return False  # Can't check, assume private

        if repo in self.repo_cache:
            return self.repo_cache[repo]

        try:
            repo_path = 'repos' if '/' in repo else 'repositories'
            url = f'{self.api_url}/{repo_path}/{repo}'
            resp = requests.get(url, headers={'Authorization': f'Bearer {self.token}'}, timeout=10)
            if resp.status_code == 200:
                self.repo_cache[repo] = not resp.json().get('private', True)
            else:
                self.repo_cache[repo] = False
        except Exception:
            self.repo_cache[repo] = False

        return self.repo_cache[repo]

    def _is_pull_request(self, owner, repo, issue_number):
        """Check if an issue number is actually a PR (caches results)."""
        if not HAS_REQUESTS or not self.token:
            return None  # Can't check

        cache_key = f"{owner}/{repo}#{issue_number}"
        if cache_key in self.pr_cache:
            return self.pr_cache[cache_key]

        try:
            url = f'{self.api_url}/repos/{owner}/{repo}/pulls/{issue_number}'
            resp = requests.get(url, headers={'Authorization': f'Bearer {self.token}'}, timeout=10)
            self.pr_cache[cache_key] = (resp.status_code == 200)
        except Exception:
            self.pr_cache[cache_key] = None

        return self.pr_cache[cache_key]

    def get_permission(self, method, path, query=None):
        """Determine required permission for an API call."""
        segments = path.split('/')

        # Filter out requests to other repositories
        if not self._is_same_repo(segments):
            return []

        # Check for OIDC token request (handled separately)
        # This is marked in the input data

        # Check special cases first
        special = self._match_special_case(method, path)
        if special:
            perm, level = special
            if '+' in perm:
                # Ambiguous - return both
                return [(p, level) for p in perm.split('+')]
            return [(perm, level)]

        # Pattern-based matching for /repos/{owner}/{repo}/{resource}
        if len(segments) >= 5 and segments[1] == 'repos':
            owner, repo, resource = segments[2], segments[3], segments[4]
            full_repo = f"{owner}/{repo}"

            # Actions
            if resource in ('actions', 'environments'):
                if method == 'GET' and self._is_public_repo(full_repo):
                    return []
                return [('actions', 'read' if method == 'GET' else 'write')]

            # Checks
            if resource in ('check-runs', 'check-suites'):
                return [('checks', 'read' if method == 'GET' else 'write')]

            # Contents
            if resource in ('releases', 'git', 'commits'):
                if method == 'GET' and self._is_public_repo(full_repo):
                    return []
                return [('contents', 'read' if method == 'GET' else 'write')]

            # Deployments
            if resource == 'deployments':
                return [('deployments', 'read' if method == 'GET' else 'write')]

            # Pages
            if resource == 'pages':
                return [('pages', 'read' if method == 'GET' else 'write')]

            # Pull requests
            if resource == 'pulls':
                return [('pull-requests', 'read' if method == 'GET' else 'write')]

            # Projects
            if resource == 'projects':
                return [('repository-projects', 'read' if method == 'GET' else 'write')]

            # Security events
            if resource == 'code-scanning':
                return [('security-events', 'read' if method == 'GET' else 'write')]

            # Statuses
            if resource == 'statuses':
                return [('statuses', 'read' if method == 'GET' else 'write')]

            # Issues with potential PR disambiguation
            if resource == 'issues' and len(segments) >= 6:
                issue_num = segments[5]
                if issue_num.isdigit():
                    is_pr = self._is_pull_request(owner, repo, issue_num)
                    if is_pr is True:
                        return [('pull-requests', 'read' if method == 'GET' else 'write')]
                    elif is_pr is False:
                        return [('issues', 'read' if method == 'GET' else 'write')]
                    # Can't determine - return both
                    return [('issues', 'read' if method == 'GET' else 'write'),
                            ('pull-requests', 'read' if method == 'GET' else 'write')]

        # Git operations via info/refs
        if len(segments) >= 5 and segments[3] == 'info' and segments[4] == 'refs':
            repo = f"{segments[1]}/{segments[2]}"
            if query:
                parsed = parse_qs(query) if isinstance(query, str) else query
                service = parsed.get('service', [''])[0]
                if service == 'git-upload-pack':
                    if self._is_public_repo(repo):
                        return []
                    return [('contents', 'read')]
                elif service == 'git-receive-pack':
                    return [('contents', 'write')]

        # Git pack operations
        if len(segments) >= 4:
            if segments[3] == 'git-upload-pack':
                repo = f"{segments[1]}/{segments[2]}"
                if self._is_public_repo(repo):
                    return []
                return [('contents', 'read')]
            elif segments[3] == 'git-receive-pack':
                return [('contents', 'write')]

        # Release downloads don't need permissions
        if len(segments) >= 5 and segments[3] == 'releases' and segments[4] == 'download':
            return []

        # Packages
        if ((len(segments) >= 4 and segments[1] in ('orgs', 'users') and segments[3] == 'packages') or
            (len(segments) >= 3 and segments[1] == 'user' and segments[2] == 'packages')):
            return [('packages', 'read' if method == 'GET' else 'write')]

        # Projects (top-level)
        if len(segments) >= 2 and segments[1] == 'projects':
            return [('repository-projects', 'read' if method == 'GET' else 'write')]

        # Repository metadata (no special permission needed)
        if len(segments) == 4 and segments[1] == 'repos' and method == 'GET':
            return []

        # Users/repositories metadata
        if len(segments) == 3 and segments[1] in ('repositories', 'users') and method == 'GET':
            return []

        # Unknown - return empty (will be flagged)
        return [('unknown', 'unknown')]

    def analyze(self, requests_data):
        """Analyze a list of API requests and return aggregated permissions."""
        permissions = {}

        for req in requests_data:
            method = req.get('method', '')
            path = req.get('path', '')
            query = req.get('query', '')
            is_oidc = req.get('oidc', False)

            if is_oidc:
                perms = [('id-token', 'write')]
            else:
                perms = self.get_permission(method, path, query)

            for perm, level in perms:
                if perm == 'unknown':
                    continue
                # Upgrade to write if needed
                if perm not in permissions or level == 'write':
                    permissions[perm] = level

        return permissions


def main():
    # Read configuration from environment
    token = os.environ.get('GITHUB_TOKEN', '')
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    api_url = os.environ.get('GITHUB_API_URL', 'https://api.github.com')

    # Read input from stdin or file argument
    if len(sys.argv) > 1:
        with open(sys.argv[1], 'r') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    analyzer = PermissionAnalyzer(token=token, repository=repository, api_url=api_url)
    permissions = analyzer.analyze(data)

    # Output as JSON
    print(json.dumps(permissions, indent=2))


if __name__ == '__main__':
    main()
