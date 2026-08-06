<script setup lang="ts">
type Variant = "module" | "section" | "plain";

const props = withDefaults(defineProps<{
    eyebrow?: string;
    title?: string;
    summary?: string;
    open: boolean;
    variant?: Variant;
}>(), {
    eyebrow: "",
    title: "",
    summary: "",
    variant: "section",
});

const emit = defineEmits<{
    (e: "toggle"): void;
}>();

const rootClass: Record<Variant, string> = {
    module: "advanced-panel module-card",
    section: "advanced-group module-card",
    plain: "advanced-group",
};

const buttonClass: Record<Variant, string> = {
    module: "advanced-group__toggle",
    section: "advanced-group__toggle",
    plain: "advanced-group__toggle",
};

const bodyClass: Record<Variant, string> = {
    module: "advanced-group__content",
    section: "advanced-group__content",
    plain: "advanced-group__content",
};

function onToggle(): void {
    emit("toggle");
}
</script>

<template>
    <div :class="rootClass[variant] || rootClass.section">
        <button :class="buttonClass[variant] || buttonClass.section" type="button" @click="onToggle">
            <span v-if="$slots.header" class="module-card__copy">
                <slot name="header" />
            </span>
            <span v-else class="module-card__copy">
                <span v-if="eyebrow" class="module-card__eyebrow">{{ eyebrow }}</span>
                <span v-if="title && variant === 'plain'" class="advanced-group__title">{{ title }}</span>
                <span v-else-if="title" class="module-card__summary">{{ title }}</span>
                <span v-if="summary && !open" class="module-card__summary">{{ summary }}</span>
            </span>
            <span class="module-card__action">{{ open ? "Hide" : "Show" }}</span>
        </button>
        <div v-if="open" :class="bodyClass[variant] || bodyClass.section">
            <slot />
        </div>
    </div>
</template>
