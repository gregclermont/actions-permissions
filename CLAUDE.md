# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains two GitHub Actions for monitoring and recommending minimal GITHUB_TOKEN permissions:

- **Monitor** (`monitor/`): Intercepts GitHub API calls during workflow execution using a transparent mitmproxy to detect which permissions are actually used
- **Advisor** (`advisor/`): Aggregates permission recommendations from multiple Monitor runs to provide consolidated advice

## Build Commands

Both actions use `@vercel/ncc` to bundle into single files:

```bash
# Build monitor action
cd monitor && npm install && npm run build

# Build advisor action
cd advisor && npm install && npm run build
```

The built output goes to `dist/index.js` in each directory.

## Architecture

### Monitor Action (`monitor/`)

1. **index.js**: Entry point that runs in two phases:
   - Initial phase: Spawns `setup.sh` to configure transparent proxy
   - Post phase (`post-if: always()`): Reads captured API calls from `/home/mitmproxyuser/out.txt`, parses permissions, generates summary, and uploads artifact

2. **setup.sh**: Linux-only setup for transparent proxy:
   - Creates `mitmproxyuser` to run proxy (avoids intercepting proxy's own traffic)
   - Installs uv, then uses it to install mitmproxy and requests
   - Configures CA certificates for various tools (Node, Python requests, curl, AWS, Elixir Hex)
   - Sets up traffic redirection via iptables

3. **mitm_plugin.py**: mitmproxy addon that:
   - Intercepts HTTP requests containing the GitHub token
   - Maps API paths to permission types using `rest_api_map` tree and pattern matching
   - Handles special cases like issues vs pull-requests disambiguation
   - Writes JSON records to output file

### Advisor Action (`advisor/`)

**index.js**: Can run as GitHub Action or CLI tool:
- Fetches workflow runs via GitHub API
- Downloads job logs to find artifact names (pattern: `{job}-permissions-{hex}`)
- Extracts permission data from artifacts
- Aggregates permissions across jobs and runs

## Key Implementation Details

- Permission mapping in `mitm_plugin.py` uses a tree structure for efficient lookup of ~167 API endpoint patterns
- Issues and pull-requests share many endpoints; the plugin makes additional API calls to disambiguate
- Only Linux runners are supported
- GraphQL API is not monitored (would require query parsing)
