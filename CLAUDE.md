# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains two GitHub Actions for monitoring and recommending minimal GITHUB_TOKEN permissions:

- **Monitor** (`monitor/`): Captures raw GitHub API calls during workflow execution
- **Advisor** (`advisor/`): Analyzes captured API calls and recommends minimal permissions

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

**Purpose**: Observe what GitHub API calls a workflow makes.

1. **`index.js`**: Entry point with two phases:
   - Initial phase: Spawns `setup.sh` to configure transparent proxy
   - Post phase: Reads captured API calls from `/home/mitmproxyuser/out.txt`, displays in summary, uploads as artifact

2. **`setup.sh`**: Linux-only setup for transparent proxy:
   - Creates `mitmproxyuser` to run proxy (avoids intercepting proxy's own traffic)
   - Installs mitmproxy via uv
   - Configures CA certificates and iptables redirection

3. **`mitm_plugin.py`**: Simple mitmproxy addon (~100 lines) that:
   - Detects requests using the GitHub token
   - Logs raw request data: `{method, host, path, query}`

### Advisor Action (`advisor/`)

**Purpose**: Analyze API calls and recommend permissions.

1. **`index.js`**: Orchestrates the analysis:
   - Downloads API call artifacts from workflow runs
   - Calls `analyze.py` via `uv run` for permission mapping
   - Displays aggregated permission recommendations

2. **`analyze.py`**: Permission analysis logic:
   - Maps API paths to permission types
   - Makes batch API calls to disambiguate issues vs PRs
   - Checks if repos are public (public repo reads need no token)

## Key Design Decisions

- **Separation of concerns**: Monitor only observes, Advisor analyzes. This keeps the proxy code simple and allows improving analysis logic without re-running workflows.
- **Raw data artifacts**: Monitor stores raw API calls, not computed permissions. This allows re-analysis with updated logic.
- **Batch disambiguation**: Issue/PR disambiguation API calls happen at analysis time, batched and deduplicated.
- **Linux-only**: Only Linux runners are supported (uses iptables for transparent proxy).
