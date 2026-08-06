<script setup lang="ts">
import { computed, ref } from "vue";
import type { ImageEntry } from "../lib/types";

const props = withDefaults(defineProps<{
    label: string;
    description?: string;
    preview?: ImageEntry | null;
    items?: ImageEntry[];
    multiple?: boolean;
}>(), {
    description: "",
    preview: null,
    items: () => [],
    multiple: false,
});

const emit = defineEmits<{
    (e: "select", files: FileList): void;
    (e: "clear"): void;
    (e: "preview", entry: ImageEntry): void;
}>();
const inputRef = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const hasSelection = computed(() => Boolean(props.preview) || props.items.length > 0);

const summary = computed(() => {
    return props.multiple
        ? (props.items.length ? `${props.items.length} file(s)` : "No files selected")
        : (props.preview?.name || "No file selected");
});

function emitSelection(files: FileList | undefined | null): void {
    if (!files || !files.length) {
        return;
    }
    emit("select", files);
}

function onPick(event: Event): void {
    const target = event.target as HTMLInputElement;
    emitSelection(target.files);
    target.value = "";
}

function onDrop(event: DragEvent): void {
    dragging.value = false;
    emitSelection(event.dataTransfer?.files);
}
</script>

<template>
    <div class="upload-card" :class="{ 'upload-card--active': dragging }" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
        <button
            v-if="preview"
            class="upload-card__preview-button"
            type="button"
            @click="$emit('preview', preview)"
        >
            <img
                class="upload-card__preview"
                :src="preview.dataUrl"
                :alt="preview.name"
            />
        </button>
        <div v-else class="upload-card__drop">
            <div class="upload-card__label">{{ label }}</div>
            <div>{{ description }}</div>
            <div class="hint">{{ summary }}</div>
        </div>
        <div class="upload-card__actions">
            <button class="btn-ghost" type="button" @click="inputRef?.click()">Select</button>
            <button
                v-if="hasSelection"
                class="btn-ghost"
                type="button"
                @click="$emit('clear')"
            >
                Clear
            </button>
            <input
                ref="inputRef"
                type="file"
                accept="image/*"
                :multiple="multiple"
                @change="onPick"
            />
        </div>
    </div>
</template>
