import os
import sys

# --- DLL Search Path Fix for CUDA on Windows ---
if sys.platform == 'win32':
    # Aggressively prioritize Torch's bundled DLL paths to avoid loading broken system-wide CUDNN
    torch_lib = os.path.join(os.getcwd(), ".venv", "Lib", "site-packages", "torch", "lib")
    if os.path.exists(torch_lib):
        # We add the torch lib to search path
        os.add_dll_directory(torch_lib)
        # We also clear system-wide NVIDIA/CUDA paths from the process's PATH to avoid confusion
        current_path = os.environ.get("PATH", "").split(os.pathsep)
        new_path = [torch_lib]
        for p in current_path:
            if "NVIDIA" not in p and "CUDA" not in p:
                new_path.append(p)
        os.environ["PATH"] = os.pathsep.join(new_path)

# --- Network Timeout Resiliency ---
os.environ["HF_HUB_READ_TIMEOUT"] = "120"
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "120"
os.environ["PIP_DEFAULT_TIMEOUT"] = "1000"

import asyncio
import websockets
import json
import logging
import io
import time
import requests
import numpy as np
import scipy.signal
# Faster-Whisper and Kokoro imports
from faster_whisper import WhisperModel
from kokoro import KPipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIPipeline")

# --- Configuration ---
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "phi3:latest"
WS_PORT = 8765

# --- State ---
class PipelineState:
    def __init__(self):
        self.audio_buffer = bytearray()
        self.turn_buffer = ""
        self.last_voice_timestamp = 0
        self.flush_task = None
        
state = PipelineState()

# --- Model Initialization ---
# Initialize Faster Whisper
# Using int8 quantization on cuda to save VRAM (RTX 3050 has 6GB)
whisper_model = WhisperModel("base", device="cuda", compute_type="int8")
logger.info("Faster-Whisper loaded.")

# Initialize Kokoro
# Load in fp16 to optimize VRAM
kokoro_pipeline = KPipeline(lang_code='a', device='cuda')
logger.info("Kokoro Pipeline loaded.")


# --- VAD & STT logic ---
def process_audio_buffer(pcm_data: bytes) -> str:
    # Android sends 16bit PCM mono at 16kHz
    audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
    
    # Simple check for silence (Energy based VAD placeholder)
    energy = np.sum(audio_np**2) / len(audio_np)
    if energy < 0.001:
        return ""
        
    logger.info("Running STT...")
    segments, info = whisper_model.transcribe(audio_np, beam_size=1)
    
    transcription = ""
    for segment in segments:
        transcription += segment.text + " "
        
    return transcription.strip()


# --- LLM Logic ---
async def call_llm(prompt: str, ws, emotion_callback):
    logger.info(f"LLM Prompt: {prompt}")
    
    payload = {
        "model": MODEL_NAME,
        "prompt": f"<|system|>\nYou are CivicBot, a friendly and extremely concise robot companion. Respond in 1-2 short sentences. Do not use technical jargon or meta-talk.\n<|user|>\n{prompt}\n<|assistant|>\n",
        "stream": True,
        "keep_alive": -1 # Keep model in memory permanently
    }
    
    # Use loop executor to avoid blocking the websocket while waiting for the slow LLM
    loop = asyncio.get_event_loop()
    try:
        def fetch_stream():
             return requests.post(OLLAMA_URL, json=payload, stream=True)

        response = await loop.run_in_executor(None, fetch_stream)
        response.raise_for_status()
        
        sentence_buffer = ""
        # The iteration itself should be done carefully
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                word = data.get("response", "")
                sentence_buffer += word
                
                # if we hit a sentence or significant pause boundary, stream to TTS
                if any(punct in word for punct in ['.', '!', '?', ';', ',']):
                    # Only chunk on comma if we have a bit of text to make it sound natural
                    if ',' in word and len(sentence_buffer) < 40:
                        continue
                        
                    await process_tts_and_send(sentence_buffer.strip(), ws)
                    sentence_buffer = ""
                    
        if sentence_buffer:
            await process_tts_and_send(sentence_buffer.strip(), ws)
            
    except Exception as e:
        logger.error(f"Ollama API error: {e}")
        await ws.send(json.dumps({"type": "llm", "text": f"Error thinking: {e}", "emotion": "sad"}))

# --- TTS Logic ---
async def process_tts_and_send(text: str, ws):
    if not text:
        return
        
    logger.info(f"Generating TTS for: {text}")
    # Notify UI
    await ws.send(json.dumps({"type": "llm", "text": text, "emotion": "talking"}))
    
    try:
        generator = kokoro_pipeline(text, voice='af_bella', speed=1)
        for i, (gs, ps, audio) in enumerate(generator):
            if audio is None:
                continue
            audio_np = audio # This is usually float32 at 24kHz
            
            # resample 24kHz to 16kHz (polyphase is faster)
            resampled_audio = scipy.signal.resample_poly(audio_np, 16000, 24000)
            
            # convert to 16-bit PCM with volume boost (loud version)
            pcm_audio = (resampled_audio * 1.5 * 32767).clip(-32768, 32767).astype(np.int16).tobytes()
            await ws.send(pcm_audio)
    except Exception as e:
        logger.error(f"TTS Error: {e}")


# --- WS Server ---
async def flush_turn(ws):
    global state
    while True:
        try:
            await asyncio.sleep(0.1)
            if state.turn_buffer and (time.time() - state.last_voice_timestamp > 0.8):
                final_transcript = state.turn_buffer.strip()
                state.turn_buffer = ""
                logger.info(f"Turn finalized: {final_transcript}")
                # Removing "Thinking" UI update as requested
                # await ws.send(json.dumps({"type": "llm", "text": f"Heard: {final_transcript}", "emotion": "thinking"}))
                
                # Start LLM response
                asyncio.create_task(call_llm(final_transcript, ws, None))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Flush loop error: {e}")
            break

async def handle_connection(ws):
    logger.info("Client connected")
    global state
    state.audio_buffer.clear()
    state.turn_buffer = ""
    state.last_voice_timestamp = 0
    
    # Start flush monitor
    flush_task = asyncio.create_task(flush_turn(ws))
    
    try:
         async for message in ws:
             if isinstance(message, bytes):
                 state.audio_buffer.extend(message)
                 
                 # Process every 1 second of audio (32000 bytes at 16kHZ 16bit)
                 if len(state.audio_buffer) >= 32000:
                     pcm_to_process = bytes(state.audio_buffer)
                     state.audio_buffer.clear()
                     
                     transcription = process_audio_buffer(pcm_to_process)
                     if transcription:
                         logger.info(f"Interim Transcription: {transcription}")
                         state.turn_buffer += transcription + " "
                         state.last_voice_timestamp = time.time()
                         
             elif isinstance(message, str):
                 logger.info(f"Received text payload: {message}")
                 
    except websockets.exceptions.ConnectionClosed:
         logger.info("Client disconnected")
    finally:
         flush_task.cancel()

async def main():
    logger.info(f"Starting server on port {WS_PORT}")
    async with websockets.serve(handle_connection, "0.0.0.0", WS_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
