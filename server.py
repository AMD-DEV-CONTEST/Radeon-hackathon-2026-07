from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import os

from main import SentinelDesk

app = FastAPI()

# Initialize the agent with TinyLlama for quick testing
print("Starting SentinelDesk API Server...")
agent = SentinelDesk(model_name="TinyLlama/TinyLlama-1.1B-Chat-v1.0", persona="helpful test agent", quantization="none")

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    # Process user input via the SentinelDesk agent
    response = agent.process_input(req.message)
    return {"response": response}

# Mount the static web directory if it exists
if os.path.exists("web"):
    app.mount("/", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
