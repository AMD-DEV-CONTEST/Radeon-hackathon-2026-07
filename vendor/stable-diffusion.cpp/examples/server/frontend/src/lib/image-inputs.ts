import type { ImageInputConfig } from "./types";

export const IMAGE_INPUTS: readonly ImageInputConfig[] = [
    {
        target: "init_image",
        label: "Init Image",
        description: "Drop, paste, or browse an image to seed generation.",
        layout: "grid",
    },
    {
        target: "mask_image",
        label: "Mask Image",
        description: "One-channel mask image.",
        layout: "grid",
    },
    {
        target: "control_image",
        label: "Control Image",
        description: "ControlNet-style guidance image.",
        layout: "full",
    },
];

export const VIDEO_IMAGE_INPUTS: readonly ImageInputConfig[] = [
    {
        target: "init_image",
        label: "Start Frame",
        description: "Optional first frame or seed image for the sequence.",
        layout: "grid",
    },
    {
        target: "end_image",
        label: "End Frame",
        description: "Optional end frame for interpolation or FLF2V-style runs.",
        layout: "grid",
    },
];
