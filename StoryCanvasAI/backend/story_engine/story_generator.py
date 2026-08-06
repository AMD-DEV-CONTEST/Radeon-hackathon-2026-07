from pathlib import Path


class StoryGenerator:

    def __init__(
        self,
        qwen_service,
        director,
        flux_service
    ):
        self.qwen = qwen_service
        self.director = director
        self.flux = flux_service

    def generate_story(self, user_prompt):

        story = self.qwen.generate(user_prompt)

        story = self.director.prepare_story(story)

        image_dir = Path("backend/generated/images")
        image_dir.mkdir(parents=True, exist_ok=True)

        for idx, page in enumerate(story["pages"], start=1):

            output = image_dir / f"page_{idx}.png"

            self.flux.generate_image(
                prompt=page["flux_prompt"],
                output_path=str(output)
            )

            page["image_path"] = str(output)

        return story