# Hamsa LiveKit Integration

A LiveKit integration for Hamsa AI's advanced Arabic speech technology, providing state-of-the-art Speech-to-Text (STT) and Text-to-Speech (TTS) capabilities with support for multiple Arabic dialects.

## 🌟 Features

- **🎙️ Advanced Arabic STT**: High-accuracy speech recognition across Arabic dialects
- **🔊 Natural Arabic TTS**: Lifelike text-to-speech with 24 Arabic voices
- **🌍 Multi-Dialect Support**: 9 Arabic dialects supported
- **⚡ Real-time Processing**: Low-latency streaming for live conversations
- **🤖 LiveKit Agent Integration**: Seamless integration with LiveKit's agent framework

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/hamsa-ai/hamsa_livekit.git
cd hamsa_livekit
pip install -e .
```

### 2. Configuration

Create a `.env` file:

```env
# LiveKit Configuration
LIVEKIT_API_KEY=your_livekit_api_key
LIVEKIT_API_SECRET=your_livekit_api_secret
LIVEKIT_URL=wss://your-project.livekit.cloud

# Hamsa AI Configuration
HAMSA_API_KEY=your_hamsa_api_key
```

## 🔧 Usage

### Basic LiveKit Agent with Hamsa

```python
from dotenv import load_dotenv
from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import openai, noise_cancellation, silero
import hamsa_livekit

load_dotenv()

class HamsaAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="You are a helpful Arabic voice assistant.")

async def entrypoint(ctx: agents.JobContext):
    await ctx.connect()

    # Create agent session with Hamsa STT and TTS
    session = AgentSession(
        stt=hamsa_livekit.STT(language="ar"),
        llm=openai.LLM(model="gpt-4"),
        tts=hamsa_livekit.TTS(speaker="Lana", dialect="jor"),
        vad=silero.VAD.load(),
        turn_detection="vad",
    )

    await session.start(
        room=ctx.room,
        agent=HamsaAssistant(),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await session.generate_reply(
        instructions="Greet the user in Arabic and offer your assistance."
    )

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
```

### Configuration Options

#### STT Configuration

```python
stt = hamsa_livekit.STT(
    language="ar",                    # Arabic language code
    api_key=None,                    # Optional API key override
    base_url="...",                  # Optional base URL override
    http_session=None                # Optional HTTP session
)
```

#### TTS Configuration

```python
tts = hamsa_livekit.TTS(
    speaker="Ali",                    # Voice speaker name (default: "Ali")
    dialect="pls",                   # Dialect code (default: "pls")
    mulaw=False,                     # μ-law encoding (default: False)
    sample_rate=16000,               # Audio sample rate (default: 16000)
    api_key=None,                    # Optional API key override
    base_url="...",                  # Optional base URL override
    word_tokenizer=None,             # Optional word tokenizer
    http_session=None                # Optional HTTP session
)
```

## 🎙️ Available Voices & Dialects

### Speakers (24 voices available)
`Amjad`, `Lyali`, `Salma`, `Mariam`, `Dalal`, `Lana`, `Jasem`, `Samir`, `Carla`, `Nada`, `Mais`, `Fatma`, `Hiba`, `Ali`, `Layan`, `Khadija`, `Mazen`, `Dima`, `Majd`, `Talin`, `Ahmed`, `Rema`, `Fahd`, `Rami`

### Dialects & Recommended Voices

| Dialect | Code | Recommended Voices |
|---------|------|-------------------|
| Palestinian | `pls` | Amjad, Layan, Talin, Rema, Ali |
| Lebanese | `leb` | Carla, Majd |
| Jordanian | `jor` | Lana, Jasem, Nada |
| Syrian | `syr` | Dalal, Mais |
| Saudi | `ksa` | Hiba, Khadija, Fahd, Jasem |
| Bahraini | `bah` | Mazen |
| Emirati | `uae` | Salma, Dima |
| Egyptian | `egy` | Mariam, Samir, Nada, Ali, Ahmed |
| Iraqi | `irq` | Lyali, Fatma |

## 📝 Quick Examples

### STT-Only Agent

```python
session = AgentSession(
    stt=hamsa_livekit.STT(language="ar"),
    llm=None,
    tts=None,
    vad=silero.VAD.load(),
    turn_detection="vad",
)
```

### TTS-Only Agent

```python
session = AgentSession(
    stt=None,
    llm=openai.LLM(model="gpt-4"),
    tts=hamsa_livekit.TTS(speaker="Mariam", dialect="egy"),
    vad=silero.VAD.load(),
    turn_detection="vad",
)
```

### Custom Audio Settings

```python
# High-quality TTS with custom sample rate
tts = hamsa_livekit.TTS(
    speaker="Amjad", 
    dialect="pls",
    sample_rate=24000,  # Higher quality
    mulaw=True          # μ-law encoding
)
```

## 🛠️ Running Your Agent

```bash
# Basic run
python your_agent.py dev

# With specific room
python your_agent.py connect --room your-room-name --token your-token
```

## 📚 API Reference

### STT Class
```python
class STT:
    def __init__(
        self,
        language: str = "ar"
    )
```

### TTS Class
```python
class TTS:
    def __init__(
        self,
        speaker: str = "Ali",
        dialect: str = "pls",
        mulaw: bool = False,
        sample_rate: int = 16000
    )
```

## 🆘 Support

- **Documentation**: [docs.tryhamsa.com](https://docs.tryhamsa.com)
- **API Reference**: [api.tryhamsa.com/docs](https://api.tryhamsa.com/docs)
- **Email**: support@hamsa.ai

---

**Built with ❤️ for the Arabic-speaking world**

*Hamsa - Where every dialect speaks the language of understanding*