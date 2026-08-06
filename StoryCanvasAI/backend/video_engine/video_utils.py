from moviepy import (
    ImageClip,
    AudioFileClip
)


def create_page_clip(page):
    """
    Creates a video clip for one story page.
    Duration is automatically taken from the narration.
    """

    audio = AudioFileClip(page["audio_path"])

    clip = (
        ImageClip(page["image_path"])
        .with_duration(audio.duration)
        .with_audio(audio)
    )

    return clip