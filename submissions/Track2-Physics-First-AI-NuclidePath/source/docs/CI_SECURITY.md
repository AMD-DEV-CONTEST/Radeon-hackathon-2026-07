# CI and runner trust boundary

## Automatic CI

Pull-request, `main` push, and ordinary manual CI run only on the GitHub-hosted
`ubuntu-24.04` image. Pull-request code is never assigned to the NuclidePath
self-hosted runner. The workflow grants `contents: read`, does not persist
checkout credentials, installs only hash-locked binary Python distributions,
pins GitHub Actions to full commit SHAs, and uses no cache, secret, or artifact
upload. Repository settings additionally keep the default workflow token
read-only and prevent workflows from approving pull requests.

## Manual PHREEQC qualification

The PHREEQC workflow is exclusively `workflow_dispatch`, rejects refs other than
`refs/heads/main`, and targets the dedicated `[self-hosted, nuclidepath]` labels.
It assumes a trusted operator. Before manually starting the runner, that operator
must inspect the Actions queue and ensure that no pull-request workflow is
approved, queued, or capable of selecting the runner. The runner should contain
the minimum possible credentials and local data. Process and workspace cleanup
belongs to a separate operating procedure.

The self-hosted runner is not claimed to be ephemeral or operating-system
isolated and is not a sandbox. An account with repository write access can alter
trusted `main` workflow code and therefore remains inside the administrative
trust boundary. The manual qualification workflow does not remove the need for
host hardening, queue inspection, and post-run cleanup.

Private-fork workflow execution is disabled for Phase F. Repository Actions are
restricted to GitHub-owned Actions and require full-length commit SHA pins.
The versioned security checker parses both `.yml` and `.yaml` structurally,
rejects any workflow outside the two-file allowlist, and enforces exact jobs,
runners, permissions, Action pins, and dependency-install commands. Its PyYAML
dependency and the lock-generator bootstrap are both versioned and hash-locked.

The checker compares the complete parsed workflow structures against versioned
canonical policy digests. This fixes the file set, top-level keys, jobs, ordered
steps, step keys, Actions, environments, and exact shell blocks; any additional
or changed step is rejected. It is a regression control, not an independent
trust root when an attacker can change the checker, tests, policy digests, and
workflow together. Code review, branch protection, repository Actions policy,
and mandatory Action SHA pins remain external controls.

## Trusted bootstrap-lock maintenance

CI consumes the already reviewed `requirements/lock-bootstrap.txt`; it does not
regenerate that root lock. Updating it is a trusted, non-recursive maintenance
operation on Linux x86_64 with Python 3.11.15 and packages obtained from the
configured Python Package Index over verified TLS:

1. Start from the currently reviewed `pip`, `pip-tools`, and `setuptools`
   versions in `requirements/lock-bootstrap.in` and a clean Python 3.11.15
   virtual environment.
2. Install the currently trusted `pip-tools` bootstrap using only reviewed
   wheels. Then run:

   ```bash
   CUSTOM_COMPILE_COMMAND='trusted bootstrap procedure in docs/CI_SECURITY.md' \
     pip-compile --allow-unsafe --generate-hashes --resolver=backtracking \
       --strip-extras --output-file=requirements/lock-bootstrap.txt \
       requirements/lock-bootstrap.in
   ```

3. Require binary distributions (`--only-binary=:all:`) when downloading every
   resulting pinned requirement, verify installation with `--require-hashes`,
   and manually review every version, SHA-256, dependency edge, and diff before
   commit.
4. To update `pip-tools` itself, first review its official release and wheel
   hash, update the input, and use the last trusted locker where compatible. If
   it cannot resolve the new release, manually verify/download the new wheel and
   dependencies in an isolated trusted environment before generating the new
   root lock.

No completely self-regenerating bootstrap can eliminate its initial trust
root. After the bootstrap lock is reviewed, `scripts/update_ci_lock.sh --check`
uses it with `--only-binary=:all:` and `--require-hashes` to reproduce the CI
lock byte-for-byte.
