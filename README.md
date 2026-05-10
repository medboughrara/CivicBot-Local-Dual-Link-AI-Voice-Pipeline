# CivicBot: Local Dual-Link AI Voice Pipeline

CivicBot is an intelligent, high-performance robot companion designed by **Mouhamed** and **Nader** as an IoT project at the **Higher Institute of Bizerte (ISB), Tunisia**. 

Designed as a civic-tech solution, CivicBot aims to bridge the gap between citizens and government by:
- **Infrastructure Reporting**: Identifying and reporting public problems (potholes, lighting, etc.).
- **Tourist Assistance**: Providing vocal guidance and information to visitors in Tunisia.
- **Elderly Support**: Assisting senior citizens with road crossings and emergency reporting.

The system features a bidirectional voice and vision pipeline between an Android endpoint and a local GPU-accelerated PC, ensuring secure, low-latency, and high-quality interaction.

![CivicBot UI](https://img.shields.io/badge/Status-Stable-brightgreen)
![Platform-Android](https://img.shields.io/badge/Platform-Android-orange)
![Backend-Python](https://img.shields.io/badge/Backend-Python-blue)

## 🎥 Project Demonstration
<center>
  <div>
    ![CivicBot Full Demonstration](civicbot_full_demo.gif)
  </div>
  
</center>




---

## 🚀 Key Features

- **Local-First Processing**: No cloud dependencies for voice processing, ensuring privacy and speed.
- **Optimized Voice Pipeline**:
  - **STT**: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (Base model) for near-instant transcription.
  - **LLM**: Integrated with [Ollama](https://ollama.com/) (Recommended: `phi3:latest` or `llama3.2:1b`).
  - **TTS**: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) for high-quality, human-like voice synthesis at 24kHz.
- **Remote Movement Control**: Real-time D-pad in the web dashboard for manual robot navigation.
- **Smart Turn-Taking**: Intelligent silence detection (0.8s threshold) to prevent interruptions and ensure fluent conversation.
- **High-Volume Audio**: Hardware-level speakerphone routing and 1.5x software gain boost for clear outdoor usability.
- **Seamless Connectivity**: Ready-to-use with Tailscale mesh networks for secure remote access.

---

## 🛠️ System Architecture

1. **Android Endpoint (`/android`)**:
   - Built with Jetpack Compose and CameraX.
   - Captures 16kHz Mono PCM audio and YUV camera frames.
   - Streams data via WebSockets to the local server.
   - Optimized with R8/Proguard for minimal footprint.

2. **PC Backend (`server.py`)**:
   - Orchestrates the AI loop using `asyncio` and `websockets`.
   - Uses `ctranslate2` for GPU-accelerated Whisper inference.
   - Implements polyphase resampling for ultra-fast 24kHz -> 16kHz audio conversion.
   - Non-blocking LLM execution via thread pools to maintain UI responsiveness.

---

## 💻 Installation & Setup

### 1. Prerequisites
- **OS**: Windows (tested) or Linux.
- **GPU**: NVIDIA RTX 3050 (6GB VRAM) or higher recommended (CUDA 12.x supported).
- **Environment**: Python 3.9+, Android Studio (for mobile build).

### 2. Backend Setup
```bash
# Clone the repository
git clone <repo-url>
cd app-main

# Create virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start Ollama (ensure phi3 is pulled)
ollama pull phi3:latest
```

### 3. Android Setup
- Open the `/android` directory in **Android Studio**.
- Ensure **Tailscale** is running on both the phone and the PC.
- Build the APK:
  ```powershell
  $env:JAVA_HOME="C:\Program Files\Android\Android Studio\jbr"
  .\gradlew assembleDebug
  ```
- Install the resulting `CivicBot_v1.0.apk` on your device.

---

## 🏃 Running the Pipeline

1. **Start the AI Server**:
   ```bash
   python server.py
   ```
2. **Launch the App**:
   - Open **CivicBot** on your Android device.
   - Ensure the IP is set to your PC's Tailscale IP (Default: `100.81.46.110`).
   - Press **START CIVIC_BOT**.
3. **Interact**:
   - Speak naturally. The robot will listen, process your request through Phi-3, and respond with high-quality synthesized speech.

---

## ⚙️ Configuration

Settings can be tuned in `server.py`:
- `MODEL_NAME`: Change the LLM (e.g., `llama3.2:1b` for maximum speed).
- `keep_alive`: Set to `-1` to keep the model loaded in VRAM permanently.
- `turn_buffer`: Adjust the 0.8s silence threshold if you speak with longer pauses.

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
*Developed with ❤️ as a local AI companion experiment.*
