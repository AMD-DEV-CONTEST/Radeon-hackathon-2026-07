import { execFileSync, spawnSync } from "node:child_process";

const hardware = run("system_profiler", ["SPHardwareDataType"]);
const display = run("system_profiler", ["SPDisplaysDataType"]);
const gitCommit = runOptional("git", ["rev-parse", "HEAD"]);
const worktreeStatus = runOptional("git", ["status", "--porcelain"]) ?? "";

const environment = {
  schema_version: "1.0",
  stage: "C0-A",
  collected_at: new Date().toISOString(),
  host: {
    os: run("sw_vers", ["-productName"]),
    os_version: run("sw_vers", ["-productVersion"]),
    os_build: run("sw_vers", ["-buildVersion"]),
    kernel: `${run("uname", ["-s"])} ${run("uname", ["-r"])}`,
    architecture: run("uname", ["-m"]),
    device_family: readField(hardware, "Model Name"),
    chip: readField(hardware, "Chip"),
    cpu_cores: readIntegerField(hardware, "Total Number of Cores"),
    memory_gb: readIntegerField(hardware, "Memory"),
    gpu: readField(display, "Chipset Model"),
    gpu_cores: readIntegerField(display, "Total Number of Cores")
  },
  tool_versions: {
    node: run("node", ["--version"]),
    npm: run("npm", ["--version"]),
    git: run("git", ["--version"]).replace(/^git version /, ""),
    docker_cli: extractDockerVersion(runOptional("docker", ["--version"])),
    git_lfs: commandPresent("git-lfs")
      ? runOptional("git-lfs", ["--version"])
      : null
  },
  amd_runtime: {
    gpu: null,
    driver: null,
    rocm_version: null,
    rocminfo_available: commandPresent("rocminfo"),
    rocm_smi_available: commandPresent("rocm-smi"),
    amd_smi_available: commandPresent("amd-smi"),
    status: "NOT_AVAILABLE_ON_LOCAL_HOST"
  },
  cloud: {
    radeon_cloud_called: false,
    shared_api_called: false,
    instance_created_or_started: false,
    credits_before: null,
    credits_after: null
  },
  source: {
    git_commit: gitCommit,
    repository_state: getRepositoryState(gitCommit, worktreeStatus),
    collector_path: "scripts/c0/collect-environment.sh"
  },
  provider_mode: "local_mock",
  remote_api: false,
  evidence_eligible: false,
  privacy: {
    hardware_serial_recorded: false,
    hardware_uuid_recorded: false,
    provisioning_udid_recorded: false,
    api_key_recorded: false
  }
};

console.log(JSON.stringify(environment, null, 2));

function run(command, args) {
  return execFileSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  }).trim();
}

function runOptional(command, args) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });
  if (result.error || result.status !== 0) {
    return null;
  }
  return result.stdout.trim();
}

function commandPresent(command) {
  const result = spawnSync(command, ["--version"], {
    stdio: "ignore"
  });
  return result.error?.code !== "ENOENT";
}

function readField(output, label) {
  const escapedLabel = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = output.match(new RegExp(`^\\s*${escapedLabel}:\\s*(.+)$`, "m"));
  return match?.[1] ?? null;
}

function readIntegerField(output, label) {
  const value = readField(output, label);
  const match = value?.match(/\d+/);
  return match ? Number.parseInt(match[0], 10) : null;
}

function extractDockerVersion(value) {
  return value?.match(/^Docker version ([^,]+)/)?.[1] ?? null;
}

function getRepositoryState(commit, status) {
  if (!commit) {
    return status
      ? "NO_COMMITS_UNCOMMITTED_WORKTREE"
      : "NO_COMMITS_CLEAN_WORKTREE";
  }
  return status ? "COMMITTED_DIRTY_WORKTREE" : "COMMITTED_CLEAN_WORKTREE";
}
