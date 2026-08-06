import os

from reportlab.platypus import SimpleDocTemplate

from StoryCanvasAI.backend.pdf_engine.pdf_utils import (
    add_cover,
    add_story_page,
)


class PDFBuilder:

    def build(
        self,
        story,
        output_path="StoryCanvasAI/backend/generated/pdf/story.pdf"
    ):

        os.makedirs(
            os.path.dirname(output_path),
            exist_ok=True
        )

        doc = SimpleDocTemplate(
            output_path
        )

        elements = []

        # ------------------------
        # Cover
        # ------------------------

        add_cover(
            elements,
            story
        )

        # ------------------------
        # Story Pages
        # ------------------------

        for page in story["pages"]:

            add_story_page(
                elements,
                page
            )

        doc.build(elements)

        print(
            f"✅ PDF saved at {output_path}"
        )