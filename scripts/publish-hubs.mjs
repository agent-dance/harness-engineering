#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const TEXT_EXTENSIONS = new Set([
  "md",
  "mdx",
  "txt",
  "json",
  "json5",
  "yaml",
  "yml",
  "toml",
  "js",
  "cjs",
  "mjs",
  "ts",
  "tsx",
  "jsx",
  "py",
  "sh",
  "rb",
  "go",
  "rs",
  "swift",
  "kt",
  "java",
  "cs",
  "cpp",
  "c",
  "h",
  "hpp",
  "sql",
  "csv",
  "ini",
  "cfg",
  "env",
  "xml",
  "html",
  "css",
  "scss",
  "sass",
  "svg"
]);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const manifestPath = path.join(repoRoot, "skills", "publish-manifest.json");

function main() {
  const options = parseArgs(process.argv.slice(2));
  const manifest = readJson(manifestPath);
  const skillEntries = selectSkills(manifest.skills, options.skills);

  if (skillEntries.length === 0) {
    console.log("No managed skills selected for this hub operation.");
    return;
  }

  console.log(`Publishing flow for: ${skillEntries.map(([slug]) => slug).join(", ")}`);

  if (options.hub === "all" || options.hub === "skills.sh") {
    validateSkillsSh(skillEntries, options);
  }

  if (options.hub === "all" || options.hub === "clawhub") {
    publishClawHub(skillEntries, options);
  }
}

function parseArgs(argv) {
  const options = {
    hub: "all",
    skills: null,
    repoUrl: "",
    bump: "patch",
    changelog: "",
    dryRun: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--hub") {
      options.hub = argv[++index] ?? "";
      continue;
    }
    if (arg.startsWith("--hub=")) {
      options.hub = arg.slice("--hub=".length);
      continue;
    }
    if (arg === "--skills") {
      options.skills = parseSkillList(argv[++index] ?? "");
      continue;
    }
    if (arg.startsWith("--skills=")) {
      options.skills = parseSkillList(arg.slice("--skills=".length));
      continue;
    }
    if (arg === "--repo-url") {
      options.repoUrl = argv[++index] ?? "";
      continue;
    }
    if (arg.startsWith("--repo-url=")) {
      options.repoUrl = arg.slice("--repo-url=".length);
      continue;
    }
    if (arg === "--bump") {
      options.bump = argv[++index] ?? "patch";
      continue;
    }
    if (arg.startsWith("--bump=")) {
      options.bump = arg.slice("--bump=".length);
      continue;
    }
    if (arg === "--changelog") {
      options.changelog = argv[++index] ?? "";
      continue;
    }
    if (arg.startsWith("--changelog=")) {
      options.changelog = arg.slice("--changelog=".length);
      continue;
    }
    if (arg === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }

  if (!["all", "skills.sh", "clawhub"].includes(options.hub)) {
    throw new Error(`Unsupported hub: ${options.hub}`);
  }
  if (!["patch", "minor", "major"].includes(options.bump)) {
    throw new Error(`Unsupported bump type: ${options.bump}`);
  }

  return options;
}

function parseSkillList(value) {
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length > 0 ? items : null;
}

function selectSkills(skills, selectedSlugs) {
  const entries = Object.entries(skills ?? {});
  if (!selectedSlugs) {
    return entries;
  }
  const selected = [];
  for (const slug of selectedSlugs) {
    if (!skills?.[slug]) {
      console.log(`Skipping unmanaged skill "${slug}" (not present in skills/publish-manifest.json).`);
      continue;
    }
    selected.push([slug, skills[slug]]);
  }
  return selected;
}

function validateSkillsSh(skillEntries, options) {
  console.log("\n== skills.sh ==");
  run("npx", ["skills", "add", ".", "--list", "--full-depth"]);

  const repoUrl = normalizeGithubUrl(options.repoUrl || gitRemoteUrl());
  if (!repoUrl) {
    console.log("No remote GitHub URL available. Skipping remote skills.sh validation.");
    return;
  }

  run("npx", ["skills", "add", repoUrl, "--list", "--full-depth"]);

  for (const [slug] of skillEntries) {
    console.log(`skills.sh page: ${buildSkillsShUrl(repoUrl, slug)}`);
  }
}

function publishClawHub(skillEntries, options) {
  console.log("\n== ClawHub ==");

  if (!options.dryRun) {
    ensureClawHubLogin();
  }

  for (const [slug, meta] of skillEntries) {
    const skillPath = path.join(repoRoot, meta.path);
    if (!existsSync(skillPath)) {
      throw new Error(`Skill path does not exist: ${meta.path}`);
    }

    const localFingerprint = buildFingerprint(buildLocalFileHashes(skillPath));
    const remote = inspectRemoteSkill(slug);
    const remoteFingerprint = remote ? buildFingerprint(remote.files) : "";

    if (remote && localFingerprint === remoteFingerprint) {
      console.log(`Skipping ${slug}: no content change versus ClawHub latest.`);
      continue;
    }

    const version = remote
      ? bumpSemver(remote.latestVersion, meta.defaultBump || options.bump || "patch")
      : meta.initialVersion;
    const changelog =
      options.changelog ||
      (remote
        ? `Automated update from ${shortSha()}`
        : `Initial ClawHub release from ${shortSha()}`);
    const tags = Array.isArray(meta.clawhubTags) && meta.clawhubTags.length > 0
      ? meta.clawhubTags.join(",")
      : "latest";

    const publishArgs = [
      "clawhub",
      "publish",
      skillPath,
      "--slug",
      slug,
      "--name",
      meta.displayName,
      "--version",
      version,
      "--tags",
      tags,
      "--changelog",
      changelog
    ];

    if (options.dryRun) {
      console.log(`[dry-run] ${formatCommand("npx", publishArgs)}`);
      continue;
    }

    run("npx", publishArgs);
    console.log(`ClawHub page: https://clawhub.ai/skills/${slug}`);
  }
}

function ensureClawHubLogin() {
  if (process.env.CLAWHUB_TOKEN) {
    run(
      "npx",
      ["clawhub", "login", "--token", process.env.CLAWHUB_TOKEN, "--no-browser"],
      { allowFailure: true }
    );
  }

  run("npx", ["clawhub", "whoami"]);
}

function inspectRemoteSkill(slug) {
  const result = run(
    "npx",
    ["clawhub", "inspect", slug, "--files", "--json"],
    { allowFailure: true }
  );

  if (result.status !== 0) {
    const combined = `${result.stdout}\n${result.stderr}`;
    if (/skill not found/i.test(combined)) {
      return null;
    }
    throw new Error(`Failed to inspect ClawHub skill "${slug}":\n${combined}`);
  }

  const data = JSON.parse(result.stdout);
  const latestVersion = data.latestVersion?.version ?? data.version?.version ?? null;
  if (!latestVersion) {
    return null;
  }

  return {
    latestVersion,
    files: Array.isArray(data.version?.files)
      ? data.version.files
          .filter((file) => typeof file?.path === "string" && typeof file?.sha256 === "string")
          .map((file) => ({ path: file.path, sha256: file.sha256 }))
      : []
  };
}

function buildLocalFileHashes(skillPath) {
  const trackedFiles = gitTrackedFiles(skillPath);
  const files = trackedFiles.length > 0 ? trackedFiles : scanLocalTextFiles(skillPath);
  const ignoreRules = loadClawHubIgnoreRules(skillPath);
  return files.map((file) => ({
    path: file.path,
    sha256: sha256(readFileSync(file.absolutePath))
  })).filter((file) => !isIgnoredByClawHub(file.path, ignoreRules));
}

function gitTrackedFiles(skillPath) {
  const relativeSkillPath = normalizePath(path.relative(repoRoot, skillPath));
  const result = run("git", ["ls-files", "--", relativeSkillPath], { allowFailure: true });
  if (result.status !== 0) {
    return [];
  }

  return result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((repoRelativePath) => {
      const absolutePath = path.join(repoRoot, repoRelativePath);
      const relativeToSkill = normalizePath(path.relative(skillPath, absolutePath));
      return { absolutePath, path: relativeToSkill };
    })
    .filter((file) => shouldIncludeFile(file.path));
}

function scanLocalTextFiles(skillPath) {
  const files = [];

  function walk(currentPath) {
    for (const entry of readdirSync(currentPath, { withFileTypes: true })) {
      if (entry.name.startsWith(".")) {
        continue;
      }
      if (entry.name === "node_modules") {
        continue;
      }
      const absolutePath = path.join(currentPath, entry.name);
      if (entry.isDirectory()) {
        walk(absolutePath);
        continue;
      }
      if (!entry.isFile()) {
        continue;
      }
      const relativeToSkill = normalizePath(path.relative(skillPath, absolutePath));
      if (!shouldIncludeFile(relativeToSkill)) {
        continue;
      }
      files.push({ absolutePath, path: relativeToSkill });
    }
  }

  walk(skillPath);
  return files.sort((left, right) => left.path.localeCompare(right.path));
}

function shouldIncludeFile(relativePath) {
  const normalized = normalizePath(relativePath);
  if (!normalized || normalized === ".") {
    return false;
  }
  const segments = normalized.split("/");
  if (segments.some((segment) => segment.startsWith("."))) {
    return false;
  }
  const extension = normalized.includes(".")
    ? normalized.split(".").pop().toLowerCase()
    : "";
  return TEXT_EXTENSIONS.has(extension);
}

function loadClawHubIgnoreRules(skillPath) {
  const ignorePath = path.join(skillPath, ".clawhubignore");
  if (!existsSync(ignorePath)) {
    return [];
  }

  return readFileSync(ignorePath, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

function isIgnoredByClawHub(relativePath, rules) {
  const normalized = normalizePath(relativePath);
  return rules.some((rule) => {
    const normalizedRule = normalizePath(rule);
    if (normalizedRule.endsWith("/")) {
      return normalized.startsWith(normalizedRule);
    }
    return normalized === normalizedRule;
  });
}

function buildFingerprint(files) {
  const payload = [...files]
    .filter((file) => file.path && file.sha256)
    .sort((left, right) => left.path.localeCompare(right.path))
    .map((file) => `${file.path}:${file.sha256}`)
    .join("\n");
  return sha256(payload);
}

function bumpSemver(version, bumpType) {
  const match = version.match(/^(\d+)\.(\d+)\.(\d+)/);
  if (!match) {
    throw new Error(`Invalid semver version: ${version}`);
  }
  const next = {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3])
  };

  if (bumpType === "major") {
    next.major += 1;
    next.minor = 0;
    next.patch = 0;
  } else if (bumpType === "minor") {
    next.minor += 1;
    next.patch = 0;
  } else {
    next.patch += 1;
  }

  return `${next.major}.${next.minor}.${next.patch}`;
}

function gitRemoteUrl() {
  const result = run("git", ["remote", "get-url", "origin"], { allowFailure: true });
  return result.status === 0 ? result.stdout.trim() : "";
}

function normalizeGithubUrl(raw) {
  if (!raw) {
    return "";
  }

  const value = raw.trim().replace(/\.git$/, "");
  if (value.startsWith("git@github.com:")) {
    return `https://github.com/${value.slice("git@github.com:".length)}`;
  }
  if (value.startsWith("https://github.com/")) {
    return value;
  }
  return "";
}

function buildSkillsShUrl(repoUrl, slug) {
  const parsed = new URL(repoUrl);
  const parts = parsed.pathname.replace(/^\/+/, "").split("/");
  return `https://skills.sh/${parts[0]}/${parts[1]}/${slug}`;
}

function shortSha() {
  if (process.env.GITHUB_SHA) {
    return process.env.GITHUB_SHA.slice(0, 7);
  }
  const result = run("git", ["rev-parse", "--short", "HEAD"], { allowFailure: true });
  return result.status === 0 ? result.stdout.trim() : "local";
}

function normalizePath(value) {
  return value.split(path.sep).join("/");
}

function readJson(filePath) {
  return JSON.parse(readFileSync(filePath, "utf8"));
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function run(command, args, options = {}) {
  const needsShell = process.platform === "win32" && ["npm", "npx"].includes(command);
  const result = needsShell
    ? spawnSync(formatCommand(command, args), {
        cwd: repoRoot,
        encoding: "utf8",
        env: process.env,
        stdio: "pipe",
        shell: true
      })
    : spawnSync(resolveCommand(command), args, {
        cwd: repoRoot,
        encoding: "utf8",
        env: process.env,
        stdio: "pipe"
      });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0 && !options.allowFailure) {
    const combined = `${result.stdout || ""}${result.stderr || ""}`.trim();
    throw new Error(`Command failed: ${formatCommand(command, args)}\n${combined}`);
  }

  return {
    status: result.status ?? 1,
    stdout: result.stdout || "",
    stderr: result.stderr || ""
  };
}

function resolveCommand(command) {
  return command;
}

function formatCommand(command, args) {
  return [command, ...args]
    .map((part) => (/\s/.test(part) ? JSON.stringify(part) : part))
    .join(" ");
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
