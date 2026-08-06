from kokoro import KPipeline
import soundfile as sf


class KokoroService:

    def __init__(
        self,
        lang_code="a",
        voice="af_heart"
    ):
        self.voice = voice
        self.pipeline = KPipeline(lang_code=lang_code)

        print("✅ Kokoro loaded successfully.")

    def generate_audio(
        self,
        text,
        output_path
    ):
        generator = self.pipeline(
            text,
            voice=self.voice
        )

        audio = None

        for _, _, audio_chunk in generator:
            audio = audio_chunk

        if audio is None:
            raise RuntimeError("No audio generated.")

        sf.write(output_path, audio, 24000)

        return output_path