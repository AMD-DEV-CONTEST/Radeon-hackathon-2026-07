import os

from moviepy import (
    concatenate_videoclips
)

from StoryCanvasAI.backend.video_engine.video_utils import (
    create_page_clip
)


class VideoBuilder:

    def build(
        self,
        story,
        output_path="StoryCanvasAI/backend/generated/videos/story.mp4",
        fps=24
    ):

        os.makedirs(
            os.path.dirname(output_path),
            exist_ok=True
        )

        clips = []

        for page in story["pages"]:

            clip = create_page_clip(page)

            clips.append(clip)

        final_video = concatenate_videoclips(
            clips,
            method="compose"
        )

        final_video.write_videofile(
            output_path,
            fps=fps,
            codec="libx264",
            audio_codec="aac"
        )

        print(f"✅ Video saved at {output_path}")

        final_video.close()

        for clip in clips:
            clip.close()