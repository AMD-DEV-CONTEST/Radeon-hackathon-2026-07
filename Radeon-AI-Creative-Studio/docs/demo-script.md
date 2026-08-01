# Radeon AI Creative Studio Demo Script

Target length: 3 to 5 minutes. Record this workflow inside the designated Radeon Cloud container.

## Shot list

1. **Opening - 0:00-0:20**
   - Show the project title and one sentence: "Radeon AI Creative Studio is a local multimodal image creation workstation powered by an AMD Radeon GPU and ROCm."

2. **Environment - 0:20-0:45**
   - Show the terminal command that prints PyTorch version, CUDA availability, and AMD GPU name.
   - Launch the app with `python app.py`.

3. **Text-to-image - 0:45-1:35**
   - Enter: `A compact cyberpunk night market in Shenzhen, rain reflections, warm shop lights, cinematic composition, editorial concept art`.
   - Show prompt preview, click Generate, and show the output plus GPU and elapsed-time panel.

4. **Image-to-image - 1:35-2:15**
   - Upload the first image as a reference.
   - Change the style or creative direction and generate a variation.
   - Show how the reference image influences the result.

5. **Batch creation - 2:15-3:00**
   - Use the same idea with batch size 2 or 4.
   - Show multiple candidates and adjacent deterministic seeds.
   - Explain that this supports fast design comparison.

6. **Enhancement - 3:00-3:35**
   - Upload a selected result.
   - Apply 2x enlargement and detail enhancement.
   - Show the before/after result and download control.

7. **Closing - 3:35-4:00**
   - Show the history gallery and the final output folder.
   - State: "The key diffusion inference stages run locally on the AMD Radeon GPU through PyTorch ROCm."

## Recording checklist

- Keep the GPU name visible in at least two shots.
- Keep the actual generation progress and final output visible.
- Do not claim that Pillow enhancement is GPU inference.
- Capture one clear screenshot of each creation mode for the PDF and poster.
- Export in 1080p if possible and keep the final video between three and five minutes.
