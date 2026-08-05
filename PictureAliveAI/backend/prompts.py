"""Mode-specific prompt templates for vision analysis and text generation."""

MODE_PROMPTS: dict[str, dict[str, str]] = {
     # ────────────────────────────────────────────────────────────
    # Education
    # ────────────────────────────────────────────────────────────
    "education": {
        "vision": (
            "Provide a rich, accessible visual description for someone who wants to learn from the image., \n"
            "Include: colors, textures, Main subject, Secondary subjects, Background, Foreground, Objects, Environment, \n"
             "depth, mood, visible text, objects., \n"
            "Be warm, clear, and evocative — like a professional faculty audio lesson."
        ),
        "text": (
           "Explain the image in detail  as a lecture to understand for a student, where you are in Futuristic smart classroom in the year 2050,, \n" 
            "holographic learning, AI teacher, students immersed in virtual lessons and providing, \n"
            "it's deep technical concepts with narration of the image in detail along, \n" 
            "with an Audio lesson and generated  5 quiz questions and sample answers with in 1500 words, for Picture Alive AI Lecture, \n" 
            "Convey your response in US English. ,\n\n"
            "Visual analysis:\n{analysis}"
        ),
    },
    # ────────────────────────────────────────────────────────────
    # Accessibility
    # ────────────────────────────────────────────────────────────
    "accessibility": {
        "vision": (
            "Provide a rich, accessible visual description for someone who cannot see it.,\n"
            "Include: colors, textures, lighting, environment, depth, mood, visible text, objects,\n"
            "people (clothing, expressions, actions), and spatial relationships.,\n"
            "Main subject, secondary subjects, emotions, human activities, facial expressions (if visible)."

        ),
        "text": (
            "Explain the image in detail to be a real life helper and guide for a blind, \n"
             "or old or medical patient to understand  the image, with a screen reader narration,, \n" 
             "emotional detections, direction, face recognition and voice guidance of the user,, \n"
              "including explanation of each distance from  each other and every object in the image in cm and feet from the user in detail, \n"
              "and at end location, country of the picture, observation of the image, \n"
              "with in 1500 words for Picture Alive AI Accessibility. Convey your response in US English.,\n\n"
              "Visual analysis:\n{analysis}"
        ),
    },
    # ────────────────────────────────────────────────────────────
    # Heritage & Tourism
    # ────────────────────────────────────────────────────────────
    "heritage_tourism": {
        "vision": (
            "Treat this as a cultural/historical artifact, sculpture,\n"
            "photograph, architectural detail, or document. Analyze: period, style,\n"
            "materials, symbolism, cultural context clues, visible text or markers."
        ),
        "text": (
            "Explain the image in detail as a tourists' audio guide narration to speak and include, \n"
             "the Landmark recognition, Historical storytelling, Architectural Marvellous, Entry fees, \n"
             "Access of the premises, Cinematic travel Audio, Studio stating and closing narrations with one possible example and at the end, \n" 
             "the place, weather, country, location details to the user, \n" 
             "within 1500 words for Picture Alive AI studio narration. Convey your response in US English in audio output.,\n\n"
            "Visual analysis:\n{analysis}"
        ),
    },
    # ────────────────────────────────────────────────────────────
    # Digital World
    # ────────────────────────────────────────────────────────────
    "digital_world": {
        "vision": (
            "Extract visual style details: color palette, lighting, weather, main subject, secondary subjects,, \n"
            "texture, Background, Objects, Estimated location, Safety hazards (if any), Any text visible inside the image., \n" 
            "For Wildlife the main vision is the wildlife, for product the main vision is the product for Picture Alive AI digital world., "
        ),
        "text": (
            "Explain the image in detail., \n" 
            "If the picture belong to Wildlife then explain the Habitant, food habit,, \n" 
            "characteristic, scientific name, Species common Name, which species family they belong, \n" 
            "Species Physical Characteristics, Behaviour towards human, History of their origin, mostly found, \n" 
            "please near the current country, current location of the species to the user within 2000 words., \n" 
            "Convey your response in US English., \n"
            "If the picture belong to any product then explain the Product name, Product Description, Product analysis,, \n" 
            "Product General details, Product Social media captions, Product features, brand Name, \n" 
            "Product impact in real world and practical real world scenarios to use of the product, technology, innovation behind the product,, \n"
            "the cost effectiveness of the product, trademark , potential users, product architecture, current location,, \n" 
            "country, year. The future growth and market potential of the product along with all the details present, \n"
            "in the images to the user within 1500 words for Picture Alive AI digital world. Convey your response in US English.,\n\n"
            "Visual analysis:\n{analysis}"
        ),
    },
    # ────────────────────────────────────────────────────────────
    # Content Creation
    # ────────────────────────────────────────────────────────────
    "content_creation": {
        "vision": (
            "Extract visual style details: color palette, lighting, composition,\n"
            "texture, facial expression, artistic influences, mood. Note everything a creative director\n"
            "would need for style-transfer, audio and video prompts."
        ),
        "text": (
            "Write a story telling for the image with characters taken from the user image, \n"
            "engaging them with conversations by narrating the image, transform the characters to an, \n" 
            "artistic behavioral podcast where the story has a real world meaning and impact in human life, \n" 
            "with example of a practical scenarios in your story. Include creativity and unique details in, \n" 
            "your story to make stand out among all. The story should have an initial background and a happy, \n" 
            "ending at the end of the story. The characters names can be unique and defines, \n" 
            "them the way a movie character get define. The story can have characters outside, \n" 
            "the user image but it should match with the flow of your story telling and it can be, \n" 
            "imaginative too. Each characters feeling and uniqueness should be covered by your story telling too for Picture Alive AI content creation., \n" 
            "Convey your response within 1500 words and in US English., \n\n"
            "Visual analysis:\n{analysis}"
        ),
    },
}
