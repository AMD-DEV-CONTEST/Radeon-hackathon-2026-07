#!/usr/bin/env bash
set -euo pipefail

VIDEO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${VIDEO_ROOT}/../.." && pwd)"
SEGMENT_ROOT="${VIDEO_ROOT}/segments_en"
OUTPUT="${VIDEO_ROOT}/smolvla_success_failure_demo.mp4"
FONT="${FONT:-/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf}"

for tool in ffmpeg ffprobe; do command -v "$tool" >/dev/null 2>&1 || { echo "error: $tool is required" >&2; exit 1; }; done
ffmpeg_filters="$(ffmpeg -hide_banner -filters 2>/dev/null)"
[[ "${ffmpeg_filters}" == *flite* ]] || { echo "error: FFmpeg flite filter is required for English narration" >&2; exit 1; }
test -f "${FONT}" || { echo "error: font not found: ${FONT}" >&2; exit 1; }
mkdir -p "${SEGMENT_ROOT}"

encode_still() {
    local input="$1" duration="$2" title="$3" subtitle="$4" narration="$5" output="$6"
    ffmpeg -y -loglevel warning -loop 1 -framerate 30 -i "${input}" \
        -f lavfi -i "flite=text='${narration}':voice=slt" \
        -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:white,drawtext=fontfile=${FONT}:text='${title}':fontcolor=white:fontsize=46:x=(w-text_w)/2:y=45:box=1:boxcolor=black@0.72:boxborderw=16,drawtext=fontfile=${FONT}:text='${subtitle}':fontcolor=#DDDDDD:fontsize=28:x=(w-text_w)/2:y=h-80:box=1:boxcolor=black@0.70:boxborderw=12,format=yuv420p[v];[1:a]volume=1.7,apad=pad_dur=${duration}[a]" \
        -map '[v]' -map '[a]' -t "${duration}" -c:v libx264 -preset veryfast -crf 20 \
        -r 30 -pix_fmt yuv420p -c:a aac -b:a 160k -ar 48000 -ac 2 "${output}"
}

encode_rollout() {
    local input="$1" title="$2" subtitle="$3" color="$4" narration="$5" output="$6"
    local source_duration duration
    source_duration="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "${input}")"
    duration="$(awk -v d="${source_duration}" 'BEGIN {print (d < 15) ? 15 : d}')"
    ffmpeg -y -loglevel warning -i "${input}" \
        -f lavfi -i "flite=text='${narration}':voice=slt" \
        -filter_complex "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:#101010,tpad=stop_mode=clone:stop_duration=15,drawtext=fontfile=${FONT}:text='${title}':fontcolor=white:fontsize=45:x=(w-text_w)/2:y=55:box=1:boxcolor=black@0.65:boxborderw=16,drawtext=fontfile=${FONT}:text='${subtitle}':fontcolor=${color}:fontsize=34:x=(w-text_w)/2:y=h-95:box=1:boxcolor=black@0.70:boxborderw=13,format=yuv420p[v];[1:a]volume=1.7,apad=pad_dur=${duration}[a]" \
        -map '[v]' -map '[a]' -t "${duration}" -c:v libx264 -preset veryfast -crf 19 \
        -r 30 -pix_fmt yuv420p -c:a aac -b:a 160k -ar 48000 -ac 2 "${output}"
}

encode_still "${PROJECT_ROOT}/docs/figures/fig10_results_dashboard.png" 12 \
    'SmolVLA Fruit Picking on AMD ROCm' 'Successes, failures, measured rates, and failure causes' \
    'This demonstration presents a SmolVLA imitation learning policy for closed loop fruit picking. We show successful rollouts, saved failure examples, measured success rates, and the main causes of failure.' \
    "${SEGMENT_ROOT}/00_title.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig5_full_pipeline.png" 15 \
    'Imitation Learning Pipeline' '600 successful expert episodes, then 20,000 SmolVLA fine tuning steps' \
    'A scripted expert generated six hundred successful episodes with domain randomization, two hundred for each fruit. SmolVLA was then fine tuned for twenty thousand steps and evaluated as the closed loop controller.' \
    "${SEGMENT_ROOT}/01_pipeline.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig6_dataset_domain_randomization.png" 15 \
    'Balanced Domain Randomized Dataset' 'Appearance, camera, pose, friction, mass, and table variations' \
    'The training set is balanced across banana, lemon, and plum. Randomized appearance, camera pose, object pose, friction, mass, and table parameters reduce dependence on one fixed simulation scene.' \
    "${SEGMENT_ROOT}/02_dataset.mp4"

encode_rollout "${VIDEO_ROOT}/success_examples/banana_success.mp4" \
    'IMITATION LEARNING POLICY - BANANA' 'SUCCESSFUL CLOSED LOOP ROLLOUT' '#66FF99' \
    'The banana rollout succeeds. In the one hundred episode benchmark, banana succeeded ninety nine times. All ten saved banana visualization rollouts succeeded, so no representative banana failure video was retained.' \
    "${SEGMENT_ROOT}/03_banana_success.mp4"

encode_rollout "${VIDEO_ROOT}/success_examples/lemon_success.mp4" \
    'IMITATION LEARNING POLICY - LEMON' 'SUCCESSFUL CLOSED LOOP ROLLOUT' '#66FF99' \
    'The same policy also picks and places the lemon. Lemon succeeded ninety four times out of one hundred in the paired HIP Graph evaluation.' \
    "${SEGMENT_ROOT}/04_lemon_success.mp4"

encode_rollout "${VIDEO_ROOT}/success_examples/plum_success.mp4" \
    'IMITATION LEARNING POLICY - PLUM' 'SUCCESSFUL CLOSED LOOP ROLLOUT' '#66FF99' \
    'This plum episode succeeds through approach, grasp, lift, transport, and release. Plum is much harder because it is smaller and less tolerant to positioning and gripper errors.' \
    "${SEGMENT_ROOT}/05_plum_success.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig3_success_rate_wilson_ci.png" 18 \
    'Measured Closed Loop Success Rates' 'Banana 99 percent, lemon 94 percent, plum 34 percent' \
    'Successful examples are not the full evaluation. Across one hundred episodes per fruit, HIP Graph achieved ninety nine percent for banana, ninety four percent for lemon, and thirty four percent for plum, for two hundred twenty seven successes overall.' \
    "${SEGMENT_ROOT}/06_success_rates.mp4"

encode_rollout "${VIDEO_ROOT}/failure_examples/lemon_failure.mp4" \
    'SAVED LEMON FAILURE' 'A rare failure among the recorded lemon rollouts' '#FF7777' \
    'This saved lemon failure shows that a high aggregate success rate does not eliminate individual failures. Small approach or grasp alignment errors can prevent a stable pickup or correct final placement.' \
    "${SEGMENT_ROOT}/07_lemon_failure.mp4"

encode_rollout "${VIDEO_ROOT}/failure_examples/plum_failure.mp4" \
    'SAVED PLUM FAILURE' 'The small object remains the main challenge' '#FF7777' \
    'Plum failures are more frequent. The small contact area makes the grasp sensitive to alignment. The object may be missed, held weakly, or dropped during transport before reaching the bowl.' \
    "${SEGMENT_ROOT}/08_plum_failure.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig9_plum_failure_distribution.png" 20 \
    'Why Plum Fails' 'Approach, grasp, lift, and transport drop are distinct failure stages' \
    'Failure stage analysis confirms the visual evidence. Approach and grasp errors remain important, while transport drop is the largest bottleneck. Residual control reduced approach failures but did not solve unstable grasping and transport.' \
    "${SEGMENT_ROOT}/09_failure_causes.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig1_system_architecture.png" 15 \
    'AMD ROCm Inference Backends' 'Eager, HIP Graph, and Targeted Compile' \
    'The policy runs on an AMD Radeon GPU through ROCm. HIP Graph accelerates the stable denoising loop while preserving dynamic inputs. Targeted Compile is faster, but its strict numerical validation shows a mismatch.' \
    "${SEGMENT_ROOT}/10_rocm.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig2_three_level_latency.png" 15 \
    'Measured Inference Acceleration' 'HIP Graph is the stable deployment candidate' \
    'Full sample actions latency decreased from one hundred fifty three point eight one milliseconds to one hundred two point seven six with HIP Graph. Targeted Compile reached sixty three point eight six milliseconds.' \
    "${SEGMENT_ROOT}/11_latency.mp4"

encode_still "${PROJECT_ROOT}/docs/figures/fig10_results_dashboard.png" 15 \
    'Evidence Based Conclusion' 'Three fruit capability, quantified limitations, and reproducible ROCm acceleration' \
    'SmolVLA demonstrates successful closed loop picking for all three fruits. Banana and lemon are reliable, while plum exposes clear grasp and transport limitations. The repository provides scripts, results, and reproducibility instructions.' \
    "${SEGMENT_ROOT}/12_closing.mp4"

cd "${VIDEO_ROOT}"
ffmpeg -y -loglevel warning -fflags +genpts -f concat -safe 0 -i concat_en.txt \
    -c:v libx264 -preset veryfast -crf 20 -r 30 -pix_fmt yuv420p \
    -c:a aac -b:a 160k -ar 48000 -ac 2 -movflags +faststart "${OUTPUT}"
echo "Generated: ${OUTPUT}"
