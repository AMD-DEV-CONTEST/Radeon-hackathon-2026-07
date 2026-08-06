import os


class AudioGenerator:

    def __init__(self, kokoro_service):
        self.kokoro = kokoro_service

    def generate(self, story):

        os.makedirs(
            "StoryCanvasAI/backend/generated/audio",
            exist_ok=True
        )

        for page in story["pages"]:

            output_path = (
                f"StoryCanvasAI/backend/generated/audio/page_{page['page']}.wav"
            )

            self.kokoro.generate_audio(
                text=page["story"],
                output_path=output_path
            )

            # Local filesystem path
            page["audio_path"] = output_path

            # Browser URL
            page["audio_url"] = (
                f"/generated/audio/page_{page['page']}.wav"
            )

        return story