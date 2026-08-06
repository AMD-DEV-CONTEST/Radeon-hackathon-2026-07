from pathlib import Path


class ImageGenerator:

    def __init__(self, flux_service):
        self.flux = flux_service

    def generate(self, story):

        image_dir = Path("StoryCanvasAI/backend/generated/images")
        image_dir.mkdir(parents=True, exist_ok=True)

        for page in story["pages"]:

            page_number = page["page"]

            output_path = image_dir / f"page_{page_number}.png"

            self.flux.generate_image(
                visual_prompt=page["clip_prompt"],
                detail_prompt=page["t5_prompt"],
                output_path=str(output_path)
            )

            # Local filesystem path
            page["image_path"] = str(output_path)

            # Browser URL
            page["image_url"] = (
                f"/generated/images/page_{page_number}.png"
            )

        return story