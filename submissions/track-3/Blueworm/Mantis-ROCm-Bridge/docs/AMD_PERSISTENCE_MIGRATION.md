# AMD persistence migration contract

Date: 2026-07-29  
Work package: `WP-AMD-PERSIST-001`  
Status: **V2 CONTRACT FROZEN; SINGLE-SESSION PVC CANARY VERIFIED**

## Decision and provenance

The participant supplied an organizer broadcast naming
`/workspace/persistence`, but the recreated official workspace proved that path
absent and exposed `/workspace/persistent -> /persistent`. The participant
explicitly adopted the observed path. One 64-byte exclusive
write-`fsync`-read-delete canary passed on the NFS PVC. The machine-readable
authority is `configs/amd-persistence-layout-v2.json`.

The destroyed instance's historical receipts and v1 contracts keep their
original `/workspace/*` paths. They describe what happened and must not be
rewritten. Future recovery uses the v2 contracts.

## Frozen durable layout

| Class | Path |
|---|---|
| Project root | `/workspace/persistent/mantis-track3` |
| Python environment | `/workspace/persistent/mantis-track3/envs/rdna` |
| Project source | `/workspace/persistent/mantis-track3/src/mantis-rocm-bridge` |
| Genesis source | `/workspace/persistent/mantis-track3/src/Genesis` |
| Datasets | `/workspace/persistent/mantis-track3/datasets` |
| Training/checkpoints | `/workspace/persistent/mantis-track3/training` |
| Receipts and run evidence | `/workspace/persistent/mantis-track3/evidence` |
| External, non-redistributable assets | `/workspace/persistent/mantis-track3/assets/external` |
| Reconstructable caches | `/workspace/persistent/mantis-track3/cache` |
| Backup staging | `/workspace/persistent/mantis-track3/backup-staging` |

Direct children of `/workspace` other than the `persistent` symlink are treated as
ephemeral. Image-provided wheels at `/` are inventoried and reinstalled on a
fresh instance; they are not experiment evidence.

## Admission order for a future instance

1. Record the fresh instance identity and current image/template.
2. Verify that `/workspace/persistent` is a symlink resolving to `/persistent`
   and that it is writable. Do not infer reset persistence from a single
   observation.
3. Run the local contract checker before creating durable outputs:

   ```bash
   PYTHONPATH=src python tools/check_amd_persistence.py \
     --check-filesystem \
     --durable-path dataset=/workspace/persistent/mantis-track3/datasets/recovery-v1 \
     --durable-path training=/workspace/persistent/mantis-track3/training/recovery-v1 \
     --durable-path evidence=/workspace/persistent/mantis-track3/evidence/recovery-v1
   ```

   This first admission gate creates no directory. After a versioned restore or
   migration has created the durable evidence directory, rerun it with a fresh
   `--output` path below that directory. A single observation still does not
   prove persistence across reset.

4. Re-inventory and hash the image-provided ROCm wheels. Freeze a fresh runtime
   config; do not relabel a prior worker's runtime as verified.
5. Restore source, the four-episode dataset, and the retained 60K inference
   checkpoint by copy into fresh versioned destinations. Verify source and
   destination SHA-256 before use.
6. Create and independently verify an off-host 219 bundle before deleting any
   source or staging copy.
7. Only then repeat project, ROCm, Genesis, LeRobot, dataset, scripted-G1, and
   training preflight gates. A separate authorization is still required for
   GPU execution.

## Fail-closed rules

- No durable dataset, checkpoint, evidence, cache, project, or asset path may
  resolve outside `/workspace/persistent`.
- Copy before delete; never move first.
- Never overwrite a previous destination.
- Keep source data until the destination and independent 219 copy both verify.
- The frozen v2 corrective-training and backup templates have old notice-path
  references and remain non-executable. A path-correct successor requires a
  later explicit work package.
- Docker-internal `/workspace` paths are not rewritten blindly. Their host bind
  source must resolve beneath the persistence root.

## Claim boundary

This work package validates the adopted path contract, current NFS PVC mount,
and one single-session write/read/delete canary. It does not prove survival
across restart or recreation, direct-local-SSD storage, that destroyed data
survived, or that any AMD workload, migration, restore, or backup was executed.
