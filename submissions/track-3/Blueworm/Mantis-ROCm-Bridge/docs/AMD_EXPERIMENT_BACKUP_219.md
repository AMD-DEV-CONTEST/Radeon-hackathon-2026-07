# Official AMD experiment backup to the 219 archive host

Date: 2026-07-27  
Contract: `configs/amd-experiment-backup-219-v1.json`  
Destination: `mid8@192.168.0.219`

> Recovery update (2026-07-29): v1 remains the immutable contract for the
> destroyed instance. Future instances use the non-executable template
> `configs/amd-experiment-backup-219-v2.json`, rooted at
> the now-superseded `/workspace/persistence/mantis-track3` notice path.
> Do not execute that template. A future successor must instead use
> `/workspace/persistent/mantis-track3`. A fresh instance identity,
> destination, source inventory, and separate execution authorization are
> required before versioning an executable successor.

## Purpose and boundary

Official Radeon Cloud PVC storage is the primary execution location, not the
only retention copy. Every terminal AMD dataset, checkpoint/output tree,
inference receipt, closed-loop episode batch, supervisor trace, and negative
result listed by the contract must be copied to the independent 219 host.

The backup is evidence retention only. It does not convert a failed experiment
into a passing result, prove that a container reproduces the cloud image, or
authorize redistribution of Mantis assets. Virtual environments and caches are
reconstructed from package receipts or the container candidate and are not
archived as experiment evidence.

## Transfer topology

The Radeon worker has no verified route to the private `192.168.0.219`
network. Use a two-hop transfer:

1. Create a fresh bundle on the AMD PVC.
2. Download the complete bundle to a fresh local staging directory.
3. Verify it locally.
4. Use key-authenticated rsync to a new `.partial` directory on 219.
5. Verify it independently on 219.
6. Rename `.partial` to the final versioned directory only after verification.

No existing source, bundle, negative evidence, or destination directory may be
overwritten.

## Build a future source bundle on AMD

The following illustrates the new root only. Do not run it with the frozen v2
template because `execution.authorized=false`. First create an execution-ready,
freshly versioned successor:

```bash
cd /workspace/persistent/mantis-track3/src/mantis-rocm-bridge
source /workspace/persistent/mantis-track3/envs/rdna/bin/activate
PYTHONPATH=src python tools/create_amd_experiment_backup_bundle.py \
  --contract configs/AMD_BACKUP_EXECUTION_READY_SUCCESSOR.json \
  --output /workspace/persistent/mantis-track3/backup-staging/BUNDLE_ID
PYTHONPATH=src python tools/verify_amd_experiment_backup_bundle.py \
  /workspace/persistent/mantis-track3/backup-staging/BUNDLE_ID \
  --receipt /workspace/persistent/mantis-track3/evidence/backup/BUNDLE_ID.verify.json
```

If any required root is missing, any symlink/special file is found, or the
output already exists, creation fails closed. Optional compact-package roots
may be absent but are recorded explicitly.

The original v1 command paths and hashes remain available in the historical
contract and receipts; they are not rewritten as if the destroyed instance
used the new layout.

## Receive and publish on 219

After downloading to a local staging path:

```bash
LOCAL_BUNDLE=/ABSOLUTE/LOCAL/mantis_amd_backup_bundle_20260727_v1
REMOTE_PARTIAL=/data/mid8/backups/mantis-track3/amd/u-11422-e97d3fd5/.mantis_amd_backup_bundle_20260727_v1.partial
REMOTE_FINAL=/data/mid8/backups/mantis-track3/amd/u-11422-e97d3fd5/mantis_amd_backup_bundle_20260727_v1

test -d "$LOCAL_BUNDLE"
ssh -i ~/.ssh/fpt26_macmini_ed25519 -o BatchMode=yes \
  mid8@192.168.0.219 "test ! -e '$REMOTE_PARTIAL' && test ! -e '$REMOTE_FINAL' && mkdir -p '$(dirname "$REMOTE_FINAL")' '$REMOTE_PARTIAL'"
rsync -a --partial --human-readable --info=progress2 \
  -e "ssh -i ~/.ssh/fpt26_macmini_ed25519 -o BatchMode=yes" \
  "$LOCAL_BUNDLE/" "mid8@192.168.0.219:$REMOTE_PARTIAL/"
```

On 219, run the verifier from a fresh source snapshot or execute
`sha256sum -c BUNDLE.SHA256SUMS` followed by the archive-content verifier.
Only after `pass=true`:

```bash
ssh -i ~/.ssh/fpt26_macmini_ed25519 -o BatchMode=yes \
  mid8@192.168.0.219 "mv '$REMOTE_PARTIAL' '$REMOTE_FINAL'"
```

Record the final directory, bundle manifest hash, byte count, verification
receipt hash, source instance ID, and UTC publication time in a versioned local
receipt.

## Container relationship

The image contains software and public project code only. Mantis URDF/meshes,
datasets, checkpoints, experiment outputs, and credentials remain external
mounts. The 219 backup therefore complements the image; it is not copied into
an image layer.
