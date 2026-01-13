console.log(`${new Date().toISOString()} Action JS started`);
const core = require('@actions/core');
const {DefaultArtifactClient} = require('@actions/artifact')
const crypto = require("crypto");
const fs = require('fs');

async function run() {
  console.log(`${new Date().toISOString()} run() called`);
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

      // Build summary table grouped by user-agent in chronological order
      let summary = core.summary.addHeading('GitHub API calls detected', 4);
      if (requests.length === 0) {
        summary.addRaw('No GitHub API calls to monitored hosts.');
      } else {
        let html = '<table>';
        let currentUA = null;
        for (const req of requests) {
          const ua = req.user_agent || 'unknown';
          if (ua !== currentUA) {
            currentUA = ua;
            html += `<tr><th colspan="3">${ua}</th></tr>`;
          }
          const label = req.oidc ? ' (OIDC)' : '';
          html += `<tr><td>${req.method}</td><td>${req.host}</td><td>${req.path}${label}</td></tr>`;
        }
        html += '</table>';
        summary.addRaw(html);
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

        // Upload debug log if it exists
        const debugLog = `${rootDir}/out-debug.txt`;
        if (fs.existsSync(debugLog)) {
          const debugData = fs.readFileSync(debugLog, 'utf8').trim();
          if (debugData) {
            const debugRequests = debugData.split('\n').map(line => JSON.parse(line));
            const debugArtifactFile = `${tempDirectory}/api-calls-debug.json`;
            fs.writeFileSync(debugArtifactFile, JSON.stringify(debugRequests, null, 2));
            await new DefaultArtifactClient().uploadArtifact(
              `${process.env['GITHUB_JOB']}-api-calls-debug-${crypto.randomBytes(16).toString("hex")}`,
              [debugArtifactFile],
              tempDirectory,
              { continueOnError: false }
            );
          }
        }
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
      const debug = core.getInput('debug') === 'true';
      const idToken = process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN || null;

      // Write config file for proxy
      const config = {
        hosts: Array.from(hosts),
        token,
        idToken,
        debug
      };
      fs.writeFileSync(`${__dirname}/../config.json`, JSON.stringify(config));

      const command = spawn('bash', ['-e', 'setup.sh'], { cwd: `${__dirname}/..` })

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
