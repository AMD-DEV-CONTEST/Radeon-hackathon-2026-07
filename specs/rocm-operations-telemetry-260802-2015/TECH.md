# Technical specification

- Level: S1
- Status: implemented

## Scope

- Normalize both current and legacy ROCm SMI JSON shapes in `HealthMonitor`.
- Collect model metadata as part of the health response.
- Add five-second visible-page polling to the system-administrator operations component.

## Design

Current ROCm images return direct byte fields (`VRAM Total Memory (B)` and `VRAM Total Used Memory (B)`), whereas earlier code only understood a legacy nested MB object. The monitor now translates both forms to the stable API response measured in MB. The health endpoint uses the already configured localhost llama.cpp endpoint; its model `meta.n_ctx` is reported as context size. GPU layer count remains zero because the OpenAI model endpoint does not expose that value.

## Risks and rollback

ROCm SMI is a short subprocess call on each health sample. It has a fifteen-second timeout and returns an empty GPU list if the tool is unavailable. Reverting these changes returns the prior manual-refresh behavior without changing report execution.

## Verification

- Focused Python Stage J tests, including a real-shape ROCm JSON parser case.
- Web production build and the existing browser/API tests.
- Strict specification validation.
