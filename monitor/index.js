const core = require('@actions/core');
const {DefaultArtifactClient} = require('@actions/artifact')
const crypto = require("crypto");
const fs = require('fs');

async function run() {
  try {
    const configString = core.getInput('config');
    let config = {};
    if (configString) {
      config = JSON.parse(configString);
    }
    if (!config.hasOwnProperty('create_artifact')) {
      config['create_artifact'] = true;
    }
    if (!config.hasOwnProperty('enabled')) {
      config['enabled'] = true;
    }

    if (!config.enabled)
      return;

    // Fail fast on unsupported OS
    if (process.env.RUNNER_OS !== 'Linux') {
      core.setFailed('Only Linux runners are supported');
      return;
    }

    if (!!core.getState('isPost')) {
      const rootDir = '/home/mitmproxyuser';

      const errorLog = `${rootDir}/error.log`;
      if (fs.existsSync(errorLog)) {
        core.setFailed(fs.readFileSync(errorLog, 'utf8'));
        process.exit(1);
      }

      const outFile = `${rootDir}/out.txt`;
      if (!fs.existsSync(outFile)) {
        core.summary.addRaw('No GitHub API calls detected.').write();
        return;
      }

      const data = fs.readFileSync(outFile, 'utf8').trim();
      if (!data) {
        core.summary.addRaw('No GitHub API calls detected.').write();
        return;
      }

      // Parse JSONL format
      const requests = data.split('\n').map(line => JSON.parse(line));

      // Deduplicate for display
      const seen = new Set();
      const uniqueCalls = [];
      for (const req of requests) {
        const key = `${req.method} ${req.path}`;
        if (!seen.has(key)) {
          seen.add(key);
          uniqueCalls.push(req);
        }
      }

      // Build summary
      let summary = core.summary.addHeading('GitHub API calls detected', 4);
      if (uniqueCalls.length === 0) {
        summary.addRaw('No GitHub API calls to monitored hosts.');
      } else {
        const lines = uniqueCalls.map(req => {
          const label = req.oidc ? ' (OIDC)' : '';
          return `${req.method} ${req.path}${label}`;
        });
        summary.addCodeBlock(lines.join('\n'), 'text');
      }
      await summary.write();

      // Upload raw log as artifact for advisor
      if (config.create_artifact) {
        const tempDirectory = process.env['RUNNER_TEMP'];
        const artifactFile = `${tempDirectory}/api-calls.json`;
        // Write as proper JSON array
        fs.writeFileSync(artifactFile, JSON.stringify(requests));
        await new DefaultArtifactClient().uploadArtifact(
          `${process.env['GITHUB_JOB']}-api-calls-${crypto.randomBytes(16).toString("hex")}`,
          [artifactFile],
          tempDirectory,
          { continueOnError: false }
        );
      }
    }
    else {
      core.saveState('isPost', true)
      const { spawn } = require('child_process');

      // Compute hosts to monitor
      const hosts = new Set();
      if (process.env.GITHUB_SERVER_URL) {
        hosts.add(new URL(process.env.GITHUB_SERVER_URL).hostname.toLowerCase());
      }
      if (process.env.GITHUB_API_URL) {
        hosts.add(new URL(process.env.GITHUB_API_URL).hostname.toLowerCase());
      }
      if (process.env.ACTIONS_ID_TOKEN_REQUEST_URL) {
        hosts.add(new URL(process.env.ACTIONS_ID_TOKEN_REQUEST_URL).hostname.toLowerCase());
      }

      const token = core.getInput('token');
      const idTokenUrl = process.env.ACTIONS_ID_TOKEN_REQUEST_URL || '';
      const idToken = process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN || '';

      const command = spawn('bash', [
        '-e', 'setup.sh',
        Array.from(hosts).join(','),
        token,
        idTokenUrl,
        idToken
      ], { cwd: `${__dirname}/..` })

      command.stdout.on('data', output => {
        console.log(output.toString())
        if (output.toString().includes('--all done--')) {
          process.exit(0)
        }
      })
      command.stderr.on('data', output => {
        console.log(`stderr: ${output.toString()}`)
      })
      command.on('exit', code => {
        if (code !== 0) {
          core.setFailed(`Exited with code ${code}`);
          process.exit(code);
        }
      })
    }
  } catch (error) {
    core.setFailed(error.message);
  }
}

run();
