import type { GenerationForm, ImageEntry, ImageTarget } from "./types";

export function readFileAsDataUrl(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ""));
        reader.onerror = () => reject(new Error(`failed to read ${file.name}`));
        reader.readAsDataURL(file);
    });
}

export async function filesToImageEntries(fileList: FileList | File[]): Promise<ImageEntry[]> {
    const files = Array.from(fileList || []);
    return Promise.all(files.map(async (file) => ({
            name: file.name,
            type: file.type || "image/png",
            dataUrl: await readFileAsDataUrl(file),
    })));
}

export function assignImageEntries(form: GenerationForm, target: ImageTarget, images: ImageEntry[]): void {
    if (target === "init_image" || target === "mask_image" || target === "control_image" || target === "end_image") {
        form[target] = images[0] || null;
        return;
    }
    if (target === "ref_images" || target === "control_frames") {
        form[target].push(...images);
    }
}

export function clearImageEntries(form: GenerationForm, target: ImageTarget): void {
    if (target === "init_image" || target === "mask_image" || target === "control_image" || target === "end_image") {
        form[target] = null;
        return;
    }
    if (target === "ref_images" || target === "control_frames") {
        form[target].splice(0);
    }
}

export function removeImageEntry(form: GenerationForm, target: ImageTarget, index: number): void {
    if (target === "ref_images" || target === "control_frames") {
        form[target].splice(index, 1);
    }
}
