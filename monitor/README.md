# GitHub token permissions Monitor action (PUBLIC BETA)

## Usage

Include the Monitor action in every job of your workflow. The action should be the first step in the job, even before the checkout action.

```yaml
...
jobs:
  job1:
    runs-on: ubuntu-latest
    steps:
      - uses: GitHubSecurityLab/actions-permissions/monitor@v1
        with:
          config: ${{ vars.PERMISSIONS_CONFIG }}

      - uses: actions/checkout@v3
...
```

The Monitor action captures all GitHub API calls made using the workflow's token and displays them in the workflow summary. The raw API call data is saved as an artifact for later analysis by the Advisor action.

To get permission recommendations, run the [Advisor action](../advisor) after collecting data from several workflow runs.

## Configuration

The Monitor action accepts a `config` input parameter. The configuration is a JSON string with the following properties:

```json
{ "create_artifact": true, "enabled": true, "debug": false }
```

* `create_artifact` - if set to `false`, the Monitor action will not create a workflow artifact with the API call log. The default value is `true`.

* `enabled` - if set to `false`, the Monitor action will not monitor API calls. The default value is `true`.

* `debug` - if set to `true`, the Monitor action will print additional debug information to the console. The default value is `false`.

If the configuration is not provided, the default values are used, but it is recommended to provide a [variable](https://docs.github.com/en/actions/learn-github-actions/variables#defining-configuration-variables-for-multiple-workflows) explicitly:

```yaml
      - uses: GitHubSecurityLab/actions-permissions/monitor@v1
        with:
          config: ${{ vars.PERMISSIONS_CONFIG }}
```

## Known limitations

* Only Linux runners are supported. macOS and Windows are not supported.

* GitHub GraphQL API usage is not monitored.

* Since the monitor runs on the Actions runner, it can't detect GitHub API calls made by third-party services that receive the token.
