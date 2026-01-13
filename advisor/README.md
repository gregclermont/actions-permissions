# GitHub token permissions Advisor action (PUBLIC BETA)

The Advisor action analyzes API call logs collected by the Monitor action and recommends the minimal permissions required for your workflow.

## Usage

* **GitHub Action**: See [workflow.yml](workflow.yml) for an example. Copy the workflow to your repository and manually dispatch it from the Actions tab.

  ![Run workflow form with input fields](../res/dispatch.png "Run workflow")

* **Command line**:

  ```bash
  export GITHUB_TOKEN=your_pat_with_repo_scope
  node index.js <workflow_name.yml> <number_of_runs> <owner> <repo> <branch> [--format yaml] [--verbose]
  ```

  Example:
  ```bash
  node index.js ci.yml 10 github actions-permissions main --format yaml --verbose
  ```

## How it works

1. Downloads API call artifacts from the last N successful workflow runs
2. Aggregates all API calls across runs and jobs
3. Analyzes each API endpoint to determine required permissions
4. For ambiguous endpoints (e.g., issues vs pull-requests), makes additional API calls to disambiguate
5. Outputs the minimal permissions needed for each job
