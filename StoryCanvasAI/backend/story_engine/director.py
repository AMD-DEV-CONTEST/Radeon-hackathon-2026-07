from .character_memory import CharacterMemory
from .prompt_composer import PromptComposer


class StoryDirector:

    def __init__(self):

        self.memory = CharacterMemory()
        self.composer = PromptComposer()

    def prepare_story(self, story_json):

        for character in story_json["characters"]:
            self.memory.add_character(character)

        for page in story_json["pages"]:
            prompts = self.composer.compose(
                page,
                self.memory
            )
            page["clip_prompt"] = prompts["clip_prompt"]
            page["t5_prompt"] = prompts["t5_prompt"]

        return story_json