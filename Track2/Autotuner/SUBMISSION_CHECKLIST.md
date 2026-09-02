# Track 2 Submission Checklist

## Eligibility and administration

1. Confirm AMD AI Developer Program membership.
2. Confirm hackathon registration.
3. Confirm participant eligibility under the official Rules and Conditions.
4. Confirm team size is no more than three.
5. Confirm every submission artifact is in English.
6. Confirm all third party model and software licenses permit the submitted use.

## Project specification

1. Application scenarios are documented.
2. Agent architecture is documented.
3. Core capabilities are documented.
4. Model choice and local deployment are documented.
5. Radeon inference optimization is documented.
6. Security, privacy, limitations, and evaluation are documented.

File: `PROJECT_SPECIFICATION.md`

Status: Complete draft

## Source code

1. Controller source is present.
2. README includes environment setup.
3. README includes startup and usage.
4. README includes dependency information.
5. Tests pass.
6. Dockerfile is present.
7. Live Radeon configuration is present.
8. Simulation configuration is present.
9. License is present.

Status: Complete draft

## Radeon evidence

1. Record exact hardware and software versions.
2. Run the baseline on Radeon.
3. Run the complete Autotuner workflow on Radeon.
4. Repeat baseline and winning presets three times.
5. Preserve raw logs and telemetry.
6. Preserve selected `rocprofv3` output.
7. Replace all metric placeholders in the video script.
8. Add the verified artifact to the submission.
9. Confirm no simulated number is described as hardware performance.

Status: Pending Radeon hardware run

## Demonstration video

1. Record three to five minutes.
2. Show command line operation.
3. Show the complete agent workflow.
4. Show local inference on Radeon.
5. Show actual Radeon execution performance.
6. Show the dashboard and final result.
7. Add English narration or English captions.
8. Upload the video to an accessible location.
9. Add the video link to `README.md`.
10. Test the link in a private browser window.

File: `DEMO_SCRIPT.md`

Status: Script complete, recording pending

## Supplementary material

Chosen format: Poster

File: `assets/poster.svg`

Status: Complete draft

## Final pull request

Required title:

```text
Track 2, Velocity, Autotuner
```

Before marking ready for review:

1. Replace simulated sample evidence or add a separate verified Radeon artifact.
2. Add the demonstration video link.
3. Review both participant names and contribution summaries.
4. Review all measured claims.
5. Confirm links work.
6. Confirm the pull request remains entirely in English.
7. Confirm the final commit contains no secrets, model tokens, private prompts, or personal keys.
