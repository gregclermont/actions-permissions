const core = require('@actions/core');
const github = require('@actions/github');
const AdmZip = require('adm-zip');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

let verbose = false;
let log = console.log;
let debug = (msg) => { if (verbose) { log(msg); } }

async function collectApiCalls(name, count, token, owner, repo, branch) {
  log(`Collecting API calls from ${name} for the last ${count} successful runs.\n`);
  const octokit = github.getOctokit(token);

  const runs = await octokit.rest.actions.listWorkflowRuns({
    owner, repo,
    workflow_id: name,
    branch,
    status: 'success',
    per_page: count,
    page: 1,
  });

  // Map of jobName -> array of API calls
  const jobCalls = new Map();

  for (const run of runs.data.workflow_runs) {
    debug(`Analyzing run ${run.id}...`);

    const jobs = await octokit.rest.actions.listJobsForWorkflowRun({
      owner, repo,
      run_id: run.id,
    });

    debug(`Found ${jobs.data.jobs.length} jobs.`);

    const artifacts = await octokit.rest.actions.listWorkflowRunArtifacts({
      owner, repo,
      run_id: run.id,
    });

    debug(`${artifacts.data.artifacts.length} artifacts...`);

    for (const job of jobs.data.jobs) {
      if (job.conclusion !== 'success') continue;

      debug(`${job.name} ${job.id} was successful...`);
      debug(`Downloading logs for job id ${job.id}...`);

      let workflowRunLog = null;
      try {
        workflowRunLog = await octokit.rest.actions.downloadJobLogsForWorkflowRun({
          owner, repo,
          job_id: job.id,
        });
      } catch (e) {
        debug(`Logs for the job ${job.id} are not available.`);
        continue;
      }

      // Look for new artifact pattern: {job}-api-calls-{hex}
      const logUploadMatch = workflowRunLog.data.match(/([^ "]+-api-calls-[a-z0-9]{32})/m);
      if (!logUploadMatch) {
        debug(`Cannot find the api-calls artifact marker. Skipping.`);
        continue;
      }

      const artifactName = logUploadMatch[1];
      debug(`Looking for artifactName ${artifactName}`);
      const jobName = artifactName.split('-').slice(0, -3).join('-');

      for (const artifact of artifacts.data.artifacts) {
        if (artifact.name === artifactName) {
          debug(`Downloading artifact id ${artifact.id}`);
          const download = await octokit.rest.actions.downloadArtifact({
            owner, repo,
            artifact_id: artifact.id,
            archive_format: 'zip',
          });

          const zip = new AdmZip(Buffer.from(download.data));
          const zipEntries = zip.getEntries();
          const extracted = zip.readAsText(zipEntries[0]);
          const apiCalls = JSON.parse(extracted);

          if (!jobCalls.has(jobName)) {
            jobCalls.set(jobName, []);
          }
          // Merge calls from this run
          jobCalls.get(jobName).push(...apiCalls);
        }
      }
    }
  }

  return jobCalls;
}

function analyzeWithPython(apiCalls, token, repository, apiUrl) {
  // Write API calls to temp file
  const tempDir = process.env.RUNNER_TEMP || '/tmp';
  const inputFile = path.join(tempDir, 'api-calls-input.json');
  fs.writeFileSync(inputFile, JSON.stringify(apiCalls));

  // Set up environment for analyze.py
  const env = {
    ...process.env,
    GITHUB_TOKEN: token,
    GITHUB_REPOSITORY: repository,
    GITHUB_API_URL: apiUrl || 'https://api.github.com',
  };

  // Run analyze.py via uv
  const scriptPath = path.join(__dirname, '..', 'analyze.py');
  try {
    // First ensure uv is available and requests is installed
    try {
      execSync('uv --version', { stdio: 'pipe' });
    } catch {
      // Install uv if not present
      execSync('curl -LsSf https://astral.sh/uv/install.sh | sh', { stdio: 'pipe', shell: true });
    }

    const result = execSync(`uv run --with requests ${scriptPath} ${inputFile}`, {
      env,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    return JSON.parse(result);
  } catch (e) {
    debug(`Python analysis failed: ${e.message}`);
    if (e.stderr) debug(e.stderr);
    throw new Error(`Failed to analyze API calls: ${e.message}`);
  }
}

async function run(token, name, count, owner, repo, branch, format) {
  const jobCalls = await collectApiCalls(name, count, token, owner, repo, branch);

  let summary = core.summary.addHeading(`Minimal required permissions for ${name}:`);
  log(`Minimal required permissions for ${name}:`);

  if (jobCalls.size === 0) {
    summary = summary.addRaw('No API call logs were found.');
    if (process.env.GITHUB_ACTIONS) {
      await summary.write();
    }
    throw new Error('No API call logs were found.');
  }

  const repository = `${owner}/${repo}`;
  const apiUrl = process.env.GITHUB_API_URL || 'https://api.github.com';

  for (const [jobName, apiCalls] of jobCalls) {
    // Analyze permissions for this job
    const permissions = analyzeWithPython(apiCalls, token, repository, apiUrl);

    summary = summary.addHeading(`${jobName}:`, 2);
    log(`---------------------= ${jobName} =---------------------`);

    let additionalIndent = format ? '  ' : '';
    if (format) console.log(`${jobName}:`);

    let codeBlock = '';
    const permEntries = Object.entries(permissions);
    if (permEntries.length === 0) {
      codeBlock += `${additionalIndent}permissions: {}`;
    } else {
      codeBlock += `${additionalIndent}permissions:\n`;
      for (const [kind, perm] of permEntries) {
        codeBlock += `${additionalIndent}  ${kind}: ${perm}\n`;
      }
    }

    console.log(codeBlock);
    summary = summary.addCodeBlock(codeBlock, 'yaml');
  }

  if (process.env.GITHUB_ACTIONS) {
    await summary.write();
  }
}

function printUsageAndExit() {
  console.log('Usage: node index.js <workflow_name.yml> <number_of_runs> <github_owner> <repo_name> <branch_name> [--format yaml] [--verbose]');
  console.log('For example: node index.js ci.yml 10 github actions-permissions main --format yaml --verbose');
  process.exit(1);
}

// Main entry point
if (process.env.GITHUB_ACTIONS) {
  const name = core.getInput('name');
  const count = core.getInput('count');
  const token = core.getInput('token');
  verbose = process.env.RUNNER_DEBUG ? true : false;
  const branch = github.context.ref.split('/').slice(-1)[0];

  run(token, name, count, github.context.repo.owner, github.context.repo.repo, branch, null).catch(error => {
    core.setFailed(error.message);
  });
} else {
  const args = process.argv.slice(2);
  let format = null;

  const formatIndex = args.indexOf('--format');
  if (formatIndex !== -1) {
    if (formatIndex + 1 >= args.length) printUsageAndExit();
    format = args[formatIndex + 1];
    if (format !== 'yaml') printUsageAndExit();
    args.splice(formatIndex, 2);
  }

  const debugIndex = args.indexOf('--verbose');
  if (debugIndex !== -1) {
    verbose = true;
    args.splice(debugIndex, 1);
  }

  if (args.length !== 5) printUsageAndExit();

  const [name, count, owner, repo, branch] = args;
  if (format !== null) log = () => {};

  run(process.env.GITHUB_TOKEN, name, count, owner, repo, branch, format).catch(error => {
    console.error(`Error: ${error.message}`);
    process.exit(2);
  });
}
