from __future__ import annotations

import asyncio
import os
import weakref
from dataclasses import dataclass
from typing import Optional

import aiohttp

from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    NotGivenOr,
)
from livekit.agents.utils import is_given

from .log import logger

BASE_URL = "https://api.tryhamsa.com/v1/realtime/tts-stream"
NUM_CHANNELS = 1


@dataclass
class _TTSOptions:
    speaker: str
    dialect: str
    mulaw: bool
    sample_rate: int
    word_tokenizer: tokenize.WordTokenizer


class TTS(tts.TTS):
    def __init__(
        self,
        *,
        speaker: str = "Ali",
        dialect: str = "pls",
        mulaw: bool = False,
        sample_rate: int = 16000,  # Hamsa typically uses 16kHz for mulaw=False
        api_key: NotGivenOr[str] = NOT_GIVEN,
        base_url: str = BASE_URL,
        word_tokenizer: NotGivenOr[tokenize.WordTokenizer] = NOT_GIVEN,
        http_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        """
        Create a new instance of Hamsa TTS.

        Args:
            speaker (str): Voice speaker to use. Defaults to "Ali".
            dialect (str): Voice dialect to use. Defaults to "pls".
            mulaw (bool): Whether to use mu-law encoding. Defaults to False.
            sample_rate (int): Sample rate of audio. Defaults to 16000.
            api_key (str): Hamsa API key. If not provided, will look for HAMSA_API_KEY in environment.
            base_url (str): Base URL for Hamsa TTS API.
            word_tokenizer (tokenize.WordTokenizer): Tokenizer for processing text.
            http_session (aiohttp.ClientSession): Optional aiohttp session to use for requests.
        """
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=sample_rate,
            num_channels=NUM_CHANNELS,
        )

        self._api_key = api_key if is_given(api_key) else os.environ.get("HAMSA_API_KEY")
        if not self._api_key:
            raise ValueError("Hamsa API key required. Set HAMSA_API_KEY or provide api_key.")

        if not is_given(word_tokenizer):
            word_tokenizer = tokenize.basic.WordTokenizer(ignore_punctuation=False)

        self._opts = _TTSOptions(
            speaker=speaker,
            dialect=dialect,
            mulaw=mulaw,
            sample_rate=sample_rate,
            word_tokenizer=word_tokenizer,
        )
        self._session = http_session
        self._base_url = base_url
        self._streams = weakref.WeakSet[SynthesizeStream]()

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def update_options(
        self,
        *,
        speaker: NotGivenOr[str] = NOT_GIVEN,
        dialect: NotGivenOr[str] = NOT_GIVEN,
        sample_rate: NotGivenOr[int] = NOT_GIVEN,
    ) -> None:
        """
        Update TTS options.
        
        Args:
            speaker (str): Voice speaker to use.
            dialect (str): Voice dialect to use.
            sample_rate (int): Sample rate of audio.
        """
        if is_given(speaker):
            self._opts.speaker = speaker
        if is_given(dialect):
            self._opts.dialect = dialect
        if is_given(sample_rate):
            self._opts.sample_rate = sample_rate
            
        for stream in self._streams:
            stream.update_options(
                speaker=speaker,
                dialect=dialect,
                sample_rate=sample_rate,
            )

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        
        return ChunkedStream(
            tts=self,
            input_text=text,
            base_url=self._base_url,
            api_key=self._api_key,
            conn_options=conn_options,
            opts=self._opts,
            session=self._ensure_session(),
        )

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> SynthesizeStream:
        stream = SynthesizeStream(
            tts=self,
            conn_options=conn_options,
            base_url=self._base_url,
            api_key=self._api_key,
            opts=self._opts,
            session=self._ensure_session(),
        )
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()
        await super().aclose()


class ChunkedStream(tts.ChunkedStream):
    def __init__(
        self,
        *,
        tts: TTS,
        base_url: str,
        api_key: str,
        input_text: str,
        opts: _TTSOptions,
        session: aiohttp.ClientSession,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._opts = opts
        self._session = session
        self._base_url = base_url
        self._api_key = api_key

    async def _run(self) -> None:
        request_id = utils.shortuuid()
        audio_bstream = utils.audio.AudioByteStream(
            sample_rate=self._opts.sample_rate,
            num_channels=NUM_CHANNELS,
        )

        try:
            payload = {
                "speaker": self._opts.speaker,
                "dialect": self._opts.dialect,
                "text": self._input_text,
                "mulaw": self._opts.mulaw,
            }
            
            async with self._session.post(
                self._base_url,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._conn_options.timeout,
            ) as res:
                if res.status != 200:
                    error_body = None
                    try:
                        error_body = await res.json()
                    except:
                        try:
                            error_body = await res.text()
                        except:
                            pass
                    
                    raise APIStatusError(
                        message=res.reason or "Unknown error occurred.",
                        status_code=res.status,
                        request_id=request_id,
                        body=error_body,
                    )

                # Stream the response chunks
                async for chunk in res.content.iter_chunked(8192):
                    if chunk:
                        for frame in audio_bstream.write(chunk):
                            self._event_ch.send_nowait(
                                tts.SynthesizedAudio(
                                    request_id=request_id,
                                    frame=frame,
                                )
                            )

                # Flush any remaining audio data
                for frame in audio_bstream.flush():
                    self._event_ch.send_nowait(
                        tts.SynthesizedAudio(request_id=request_id, frame=frame)
                    )

        except asyncio.TimeoutError as e:
            raise APITimeoutError() from e
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message,
                status_code=e.status,
                request_id=request_id,
                body=None,
            ) from e
        except Exception as e:
            raise APIConnectionError() from e


class SynthesizeStream(tts.SynthesizeStream):
    def __init__(
        self,
        *,
        tts: TTS,
        base_url: str,
        api_key: str,
        opts: _TTSOptions,
        session: aiohttp.ClientSession,
        conn_options: APIConnectOptions,
    ):
        super().__init__(tts=tts, conn_options=conn_options)
        self._opts = opts
        self._session = session
        self._base_url = base_url
        self._api_key = api_key
        self._current_request: Optional[asyncio.Task] = None

    def update_options(
        self,
        *,
        speaker: NotGivenOr[str] = NOT_GIVEN,
        dialect: NotGivenOr[str] = NOT_GIVEN,
        sample_rate: NotGivenOr[int] = NOT_GIVEN,
    ) -> None:
        if is_given(speaker):
            self._opts.speaker = speaker
        if is_given(dialect):
            self._opts.dialect = dialect
        if is_given(sample_rate):
            self._opts.sample_rate = sample_rate

    async def _run(self) -> None:
        audio_bstream = utils.audio.AudioByteStream(
            sample_rate=self._opts.sample_rate,
            num_channels=NUM_CHANNELS,
        )

        @utils.log_exceptions(logger=logger)
        async def _process_input():
            # Accumulate text and synthesize in chunks
            accumulated_text = ""
            
            async for input_data in self._input_ch:
                if isinstance(input_data, str):
                    accumulated_text += input_data
                    
                    # Check if we have a complete sentence or phrase to synthesize
                    if any(punct in accumulated_text for punct in ['.', '!', '?', '\n']):
                        if accumulated_text.strip():
                            await self._synthesize_text(accumulated_text.strip(), audio_bstream)
                        accumulated_text = ""
                        
                elif isinstance(input_data, self._FlushSentinel):
                    # Synthesize any remaining text
                    if accumulated_text.strip():
                        await self._synthesize_text(accumulated_text.strip(), audio_bstream)
                    accumulated_text = ""

        await _process_input()

    async def _synthesize_text(self, text: str, audio_bstream: utils.audio.AudioByteStream):
        """Synthesize a chunk of text and emit audio frames."""
        request_id = utils.shortuuid()
        
        try:
            payload = {
                "speaker": self._opts.speaker,
                "dialect": self._opts.dialect,
                "text": text,
                "mulaw": self._opts.mulaw,
            }
            
            self._mark_started()
            
            async with self._session.post(
                self._base_url,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._conn_options.timeout,
            ) as res:
                if res.status != 200:
                    logger.error(f"Hamsa TTS API error: {res.status} - {res.reason}")
                    return

                # Stream the response chunks
                async for chunk in res.content.iter_chunked(8192):
                    if chunk:
                        for frame in audio_bstream.write(chunk):
                            self._event_ch.send_nowait(
                                tts.SynthesizedAudio(
                                    request_id=request_id,
                                    frame=frame,
                                )
                            )

                # Flush any remaining audio data for this chunk
                for frame in audio_bstream.flush():
                    self._event_ch.send_nowait(
                        tts.SynthesizedAudio(request_id=request_id, frame=frame)
                    )

        except Exception as e:
            logger.error(f"Error synthesizing text chunk: {e}")