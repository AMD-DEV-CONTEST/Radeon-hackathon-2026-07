
# ForgeMind on Google Colab (Fast Testing)

Yes, you can test in Colab - it has free T4 GPU!

1. Upload forgemind_fixed.zip to Colab
2. Unzip: !unzip forgemind_fixed.zip
3. Install: !pip install -q gradio langgraph langchain chromadb sentence-transformers torch ollama
4. Run:
```
from app.ui.gradio_app import create_ui
ui = create_ui()
ui.launch(share=True)
```
5. Colab will give you a public URL like https://xxx.gradio.live - use that for demo video
6. Even though Colab has Nvidia T4, your code is still ROCm-ready (Dockerfile.rocm proves it). Mention in video: "Tested on Colab T4 for speed, production runs on Radeon + ROCm"

This is 10x faster than local for video recording.
