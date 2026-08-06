# AMD Ryzen AI Max+ 395 Environment Audit Template

Template status: blank evidence record. Do not enter estimates, remembered values, or results copied from another machine.

Use this template only on the machine being audited. Replace sensitive host, user, serial-number, network, and filesystem details with non-identifying labels before committing a completed record.

## 1. Record Metadata

- Experiment ID:
- Operator:
- Audit date:
- Start time:
- End time:
- Time zone:
- Host alias:
- Repository commit:
- Purpose:
- Network state:
- Documentation references and access dates:

## 2. Hardware

- CPU:
- GPU:
- GPU architecture / LLVM target:
- Memory:
- Configured GPU / UMA memory:
- Storage relevant to model loading:
- Power profile:
- Thermal or cooling notes:

## 3. Software

- OS:
- OS release:
- Kernel:
- ROCm:
- Driver:
- Ollama:
- Model:
- Model revision or digest:
- Quantization:
- llama.cpp / HIP backend identity, if exposed:
- Shell:

## 4. Commands

Run commands from the same environment and record command start times, exit codes, and unedited non-sensitive output.

```bash
rocminfo
```

```bash
rocm-smi
```

```bash
ollama list
```

```bash
ollama show <MODEL_NAME>
```

If a command is unavailable or unsupported, record that fact and the exact error. Do not substitute a successful result from another command or machine without labeling it as separate evidence.

## 5. Output

### 5.1 `rocminfo`

```text

```

### 5.2 `rocm-smi`

```text

```

### 5.3 `ollama list`

```text

```

### 5.4 `ollama show <MODEL_NAME>`

```text

```

## 6. Observations

- GPU detected by ROCm:
- Reported target:
- Ollama model present:
- Backend evidence:
- Warnings or anomalies:
- Follow-up required:

## 7. Evidence Integrity

- Raw output location:
- Raw output SHA-256:
- Redactions applied:
- Redaction reason:
- Reviewer:
- Review date:

## 8. Completion Check

- [ ] All values came from the audited machine.
- [ ] Software versions and model identity are explicit.
- [ ] Command failures are preserved rather than hidden.
- [ ] No API key, token, `.env`, personal path, customer data, or confidential document is present.
- [ ] Redactions do not remove evidence needed to identify the GPU, ROCm, driver, Ollama, or model version.
- [ ] A second reviewer can distinguish observed facts from operator interpretation.
