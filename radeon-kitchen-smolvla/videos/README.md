# Demo Video

Public video URL: https://youtu.be/N06ePLwqoqk

Final local render: `radeon_kitchen_smolvla_final_demo_intensity_sweep.mp4`
(132 seconds, 1920x1080, English narration, bilingual on-screen text). The earlier
`radeon_kitchen_smolvla_demo_preview.mp4` is preserved separately.
The 100-second `radeon_kitchen_smolvla_final_demo.mp4` is also preserved as a
fallback cut.

Use demo_script.md as the narration and editing plan. The final video must be
3 minutes or shorter, include both success and failure clips, and end with the
GitHub URL and team name.

Recommended evidence to include:

- Best success video from output/eval/kitchen_eval_prompt_cube/videos/
- One failure video from output/eval/kitchen_eval_prompt_cube/videos/
- analysis/failure_coordinate_scatter.svg
- analysis/robustness/robustness_intensity_envelope.svg
- The final render's nominal-versus-40%-occlusion four-panel clip
- The experiment table from README.md or analysis/eval_comparison.md

The stress comparison uses clips recorded from the exact perturbed observations
fed to the policy. The bottom row therefore shows the localized rectangular
occlusion itself, rather than a clean post-action render.
