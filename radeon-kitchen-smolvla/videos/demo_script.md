# Demo Video Script

Target duration: 2 minutes 12 seconds (must be no longer than 3 minutes).

## 0:00-0:05 - Task

Show the successful pick before explaining the method.

Narration:

> This is a vision-language-action policy for a Franka Panda robot. The task
> is simple to describe: pick up the cube. The challenge is keeping the
> action stable in a closed loop.

## 0:05-0:29 - Pipeline

Show the title, Genesis expert data, LeRobot fields, SmolVLA fine-tuning, and
the synchronized overhead and wrist views.

Narration:

> We generate scripted expert trajectories in Genesis, store synchronized
> state, action, image, and task fields in LeRobot format, fine-tune SmolVLA
> on AMD Radeon ROCm, and evaluate the policy back in the same kitchen.

## 0:29-0:52 - Results and failure

Show the controlled result cards, then one failure clip.

Narration:

> The aligned prompt baseline reached 55 percent on 20 seed-99 episodes. A
> prompt mismatch scored 35 percent, eight thousand effective steps scored
> 40 percent, and the second seed scored 5 percent. Loss alone is not the
> task metric, so we keep the failure in the story.

## 0:52-1:08 - Failure coordinates

Show `analysis/failure_coordinate_scatter.svg` and the targeted-data rationale.

Narration:

> The failure plot maps the cube placement for every episode. Failures cluster
> near far reach and lateral boundaries. Targeted-only fine-tuning collapsed
> to 5 percent, which motivates broad replay instead of replacing the data
> distribution.

## 1:08-1:26 - Multi-strength robustness envelope

Show `analysis/robustness/robustness_intensity_envelope.svg`.

Narration:

> We sweep perturbation intensity instead of reporting one stressed success
> rate. Every point uses the same placement manifest and 20 episodes. The
> clearest envelope is local occlusion: success falls from 20 to 5 to 0
> percent as the masked image side length grows from 10 to 25 to 40 percent.
> The other curves stay unsmoothed because they are binomial estimates.

## 1:26-1:40 - Visual mechanism

Show the four-panel nominal versus 40 percent occlusion clip.

Narration:

> The top row has normal observations. The bottom row masks visual evidence
> in both cameras. In the short probe, nominal completes one of three episodes
> while the occluded condition completes zero. This is the mechanism behind
> the red curve, not just a number in a table.

## 1:40-1:52 - Failure-aware replay

Show the mixed replay card.

Narration:

> We generated hard cases from failure coordinates and mixed them with broad
> replay at two to one. The candidate scored 20 percent on the paired 50
> episode set, below the baseline's 42 percent, so we reject it and preserve
> the original 4,000-step checkpoint.

## 1:52-2:04 - Sim-to-Real limits

Show the calibration plan.

Narration:

> These are Genesis results, not a real-robot guarantee. Real transfer needs
> camera calibration, contact identification, controller latency matching,
> and guarded low-speed tests.

## 2:04-2:12 - Closing

Show the repository URL, team name, and track.

Narration:

> The deliverable is an open reproducible AMD ROCm workflow from synthetic
> expert data to closed-loop VLA evaluation, with measured transfer risks.

Final frame:

- GitHub: `https://github.com/ryantryor/Radeon-hackathon-2026-07/tree/main/radeon-kitchen-smolvla`
- Team: Chen Weiliang
- Track: Physical AI Challenge

## Editing Checklist

- Open with a real successful pick.
- Include both overhead and wrist views.
- Include at least one failure clip.
- Show the current metrics without hiding the seed-123 result.
- Show the failure coordinate plot.
- Show the fixed-manifest and mixed-replay commands.
- Keep the final video at or below 3 minutes.
- Show nominal and stressed success as separate numbers; never label a planned
  experiment as a completed result.
- Add Chinese subtitles during editing if a bilingual cut is required.
