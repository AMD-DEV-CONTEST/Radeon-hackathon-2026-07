class PromptComposer:

    def compose(self, page, character_memory):

        # Short prompt for CLIP (77-token encoder)
        clip_prompt = (
            f"{page['image_prompt']}"
            "children's storybook animation, CARTOON ,cinematic lighting,colourful"
        )

        # Detailed prompt for T5 (long-context encoder)
        t5_prompt = (
            "Consistent characters.\n\n"
        )

        for character in page["characters"]:

            info = character_memory.get_character(character)
            if not info:
                continue

            t5_prompt += (
                f"{info['name']} is a "
                f"{info['age']}-year-old "
                f"{info['gender']} "
                f"{info['species']} with "
                f"{info['hair']}, coloured hair"
                f"{info['eyes']} eyes, "
                f"wearing {info['clothes']}, "
                f"carrying {info['accessories']}.\n"
            )
        t5_prompt += f"\nScene: {page['image_prompt']}"
        return {
            "clip_prompt": clip_prompt,
            "t5_prompt": t5_prompt
        }