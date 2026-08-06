class CharacterMemory:

    def __init__(self):
        self.characters = {}

    def add_character(self, character):

        self.characters[character["name"]] = character

    def get_character(self, name):

        return self.characters.get(name)

    def all(self):

        return self.characters