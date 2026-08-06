from StoryCanvasAI.backend.story_engine.director import StoryDirector
from StoryCanvasAI.backend.image_engine.image_generator import ImageGenerator
from StoryCanvasAI.backend.prompts.story_prompt import STORY_PROMPT
from StoryCanvasAI.backend.audio_engine.audio_generator import AudioGenerator
from StoryCanvasAI.backend.pdf_engine.pdf_builder import PDFBuilder
from StoryCanvasAI.backend.video_engine.video_builder import VideoBuilder
import os
import json
class StoryPipeline:

    def __init__(self, qwen_service, flux_service,kokoro_service):

        self.qwen = qwen_service
        self.director = StoryDirector()
        self.image_generator = ImageGenerator(flux_service)
        self.audio_generator = AudioGenerator(kokoro_service)
        self.pdf_builder = PDFBuilder()
        self.video_builder = VideoBuilder()
    def generate(self, user_prompt, pages=5):

        print(">>> ENTER generate()")

        prompt = STORY_PROMPT.format(
            pages=pages,
            user_prompt=user_prompt
        )

        print(">>> Calling Qwen")

        story = self.qwen.generate(prompt)

        print(">>> Qwen finished")

        story = self.director.prepare_story(story)

        print(">>> Director finished")

        story = self.image_generator.generate(story)

        print(">>> Images finished")

        story = self.audio_generator.generate(story)

        print(">>> Audio finished")

        os.makedirs("StoryCanvasAI/backend/generated/stories", exist_ok=True)

        with open(
            "StoryCanvasAI/backend/generated/stories/story.json",
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                story,
                f,
                indent=4,
                ensure_ascii=False
            )

        print(">>> JSON saved")

        self.pdf_builder.build(story)

        print(">>> PDF built")

        self.video_builder.build(story)

        print(">>> Video built")

        print(">>> Returning story")

        return story