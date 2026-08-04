# Radeon AI Creative Studio Demo Script

Target length: 3 to 5 minutes. Record this workflow inside the designated Radeon Cloud container.

## Shot list

1. **Opening - 0:00-0:20**
   - Show the project title and one sentence: "Radeon AI Creative Studio is a local multimodal image creation workstation powered by an AMD Radeon GPU and ROCm."

2. **Environment - 0:20-0:45**
   - Show the terminal command that prints PyTorch version, CUDA availability, AMD GPU name, and ROCm/HIP version.
   - Launch the app with `python app.py`.

3. **Text-to-image - 0:45-1:35**
   - Use the Interior Design creative type and Watercolor Illustration style.
   - Enter: `A sunlit modern French living room, floor-to-ceiling windows, a beige sofa, and elegant pendant lights`.
   - Use 512x512 resolution, 25 steps, and seed `1065119644`.
   - Show the generated image, GPU information, and the 2.14-second elapsed-time panel.

4. **Image-to-image - 1:35-2:15**
   - Upload the generated living-room image as a reference.
   - Use the Luxury French target style, strength 0.55, 512x512 resolution, 25 steps, and seed `1131595709`.
   - Show the reference image, transformed result, GPU information, and the 0.84-second elapsed-time panel.

5. **Batch creation - 2:15-3:00**
   - Use the Concept Art creative type, Traditional Chinese style, Fast quality, and batch size 4.
   - Use 512x512 resolution, 15 steps, and base seed `2006462266`.
   - Show four candidates and adjacent deterministic seeds `2006462266` through `2006462269`.
   - Show the AMD GPU batch information and the 284.11-second total inference time.

6. **Enhancement - 3:00-3:35**
   - Upload the living-room reference image.
   - Apply 2x enlargement, automatic contrast, and detail enhancement.
   - Show the 512x512 before image, 1024x1024 after image, processing information, and download control.
   - Explain that this completed in 0.08 seconds as deterministic local CPU post-processing.

7. **Closing - 3:35-4:00**
   - Show the history gallery and the final output folder.
   - State: "The key diffusion inference stages run locally on the AMD Radeon GPU through PyTorch ROCm."

## Recording checklist

- Keep the GPU name visible in at least two shots.
- Keep the actual generation progress and final output visible.
- Do not claim that Pillow enhancement is GPU inference.
- Capture one clear completed-state screenshot of each creation mode for the PDF and poster.
- Export in 1080p if possible and keep the final video between three and five minutes.
