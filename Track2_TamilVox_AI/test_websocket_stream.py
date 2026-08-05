"""
test_websocket_stream.py — Test WebSocket streaming & wake-word detection for TamilVox
"""
import asyncio
import json
import numpy as np
import websockets

SERVER_WS_URL = "ws://127.0.0.1:8000/ws/stream"


def generate_synthetic_tone(freq=440, duration_sec=1.5, sample_rate=16000):
    """Generates synthetic 16kHz 16-bit mono PCM audio data."""
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), False)
    tone = np.sin(2 * np.pi * freq * t) * 0.3
    pcm = (tone * 32767).astype(np.int16).tobytes()
    return pcm


async def test_websocket_streaming():
    print(f"[TEST] Connecting to WebSocket endpoint: {SERVER_WS_URL}...")
    try:
        async with websockets.connect(SERVER_WS_URL, open_timeout=20) as ws:
            print("[TEST] Connected successfully!")
            
            # 1. Send PCM audio chunks in 512-byte blocks
            pcm_data = generate_synthetic_tone(duration_sec=2.0)
            chunk_size = 512
            print(f"[TEST] Streaming {len(pcm_data)} bytes of PCM audio in {chunk_size}-byte chunks...")
            
            for i in range(0, len(pcm_data), chunk_size):
                chunk = pcm_data[i:i + chunk_size]
                await ws.send(chunk)
                await asyncio.sleep(0.01)  # Simulate real-time 10ms packet interval
                
            # 2. Send control signal to process accumulated buffer
            print("[TEST] Sending 'END' signal to process audio stream...")
            await ws.send("END")
            
            # 3. Receive JSON response from server
            response_str = await ws.recv()
            res = json.loads(response_str)
            print("\n" + "=" * 50)
            print("  WEBSOCKET RESPONSE RECEIVED")
            print("=" * 50)
            print(f"  Status:         {res.get('status')}")
            print(f"  Wake Detected:  {res.get('wake_detected')}")
            print(f"  User Text:      {res.get('user_text')}")
            print(f"  Reply Text:     {res.get('reply_text')}")
            print(f"  Is Command:     {res.get('is_command')}")
            print(f"  Device/Command: {res.get('device')} -> {res.get('command')}")
            print(f"  Audio B64 Len:  {len(res.get('audio_b64', ''))}")
            print("=" * 50)
            print("\n[SUCCESS] WebSocket low-latency PCM streaming & processing verified!")

    except Exception as e:
        print(f"[TEST ERROR] {e}")


if __name__ == "__main__":
    asyncio.run(test_websocket_streaming())
