# Copyright 2023 LiveKit, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Speech-to-Text implementation for Hamsa

This module provides an STT implementation that uses the Hamsa API.
"""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass
from typing import Any

import aiohttp

from livekit import rtc
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    stt,
    utils,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import AudioBuffer

from .log import logger

# Hamsa API details
HAMSA_STT_BASE_URL = "https://api.tryhamsa.com/v1/realtime/stt"


@dataclass
class HamsaSTTOptions:
    """Options for the Hamsa STT service.

    Args:
        language: Language code, e.g., "ar", "en"
        api_key: Hamsa API key
        base_url: API endpoint URL
    """

    language: str
    api_key: str | None = None
    base_url: str = HAMSA_STT_BASE_URL


class STT(stt.STT):
    """Hamsa Speech-to-Text implementation.

    This class provides speech-to-text functionality using the Hamsa API.

    Args:
        language: Language code, e.g., "ar", "en"
        api_key: Hamsa API key (falls back to HAMSA_API_KEY env var)
        base_url: API endpoint URL
        http_session: Optional aiohttp session to use
    """

    def __init__(
        self,
        *,
        language: str = "ar",
        api_key: str | None = None,
        base_url: str = HAMSA_STT_BASE_URL,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        super().__init__(capabilities=stt.STTCapabilities(streaming=False, interim_results=False))

        self._api_key = api_key or os.environ.get("HAMSA_API_KEY")
        if not self._api_key:
            raise ValueError(
                "Hamsa API key is required. "
                "Provide it directly or set HAMSA_API_KEY environment variable."
            )

        self._opts = HamsaSTTOptions(
            language=language,
            api_key=self._api_key,
            base_url=base_url,
        )
        self._session = http_session
        self._logger = logger.getChild(self.__class__.__name__)

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def _convert_to_wav_base64(self, buffer: AudioBuffer) -> str:
        """Convert audio buffer to WAV format at 16kHz and encode as base64."""
        # Use LiveKit's built-in method to convert to WAV
        # This handles all the resampling and format conversion automatically
        wav_bytes = rtc.combine_audio_frames(buffer).to_wav_bytes()
        return base64.b64encode(wav_bytes).decode('utf-8')

    async def _recognize_impl(
        self,
        buffer: AudioBuffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> stt.SpeechEvent:
        """Recognize speech using Hamsa API.

        Args:
            buffer: Audio buffer containing speech data
            language: Language code (overrides the one set in constructor)
            conn_options: Connection options for API requests

        Returns:
            A SpeechEvent containing the transcription result

        Raises:
            APIConnectionError: On network connection errors
            APIStatusError: On API errors (non-200 status)
            APITimeoutError: On API timeout
        """
        opts_language = self._opts.language if isinstance(language, type(NOT_GIVEN)) else language

        # Convert audio to WAV base64 format
        try:
            audio_base64 = self._convert_to_wav_base64(buffer)
        except Exception as e:
            self._logger.error(f"Failed to convert audio to WAV base64: {e}")
            raise APIConnectionError(f"Audio conversion error: {e}") from e

        # Prepare request payload
        payload = {
            "audioBase64": audio_base64,
            "language": opts_language,
            "isEosEnabled": False,
            "eosThreshold": 0.3,
        }

        headers = {
            "Authorization": f"Token {self._opts.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LiveKit Agents",
        }

        try:
            async with self._ensure_session().post(
                url=self._opts.base_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(
                    total=conn_options.timeout,
                    sock_connect=conn_options.timeout,
                ),
            ) as res:
                if res.status != 200:
                    error_text = await res.text()
                    self._logger.error(f"Hamsa API error: {res.status} - {error_text}")
                    raise APIStatusError(
                        message=f"Hamsa API Error: {error_text}",
                        status_code=res.status,
                    )

                response_json = await res.json()
                self._logger.debug(f"Hamsa API response: {response_json}")

                # Parse response based on Hamsa API format
                transcript_text = ""
                if response_json.get("success") and response_json.get("data"):
                    transcript_text = response_json["data"].get("text", "")

                # Calculate duration from buffer for timing
                start_time = 0.0
                end_time = 0.0
                try:
                    if isinstance(buffer, list):
                        # Calculate total duration from all frames
                        total_samples = sum(frame.samples_per_channel for frame in buffer)
                        if buffer and total_samples > 0:
                            sample_rate = buffer[0].sample_rate
                            end_time = total_samples / sample_rate
                    elif hasattr(buffer, "samples_per_channel") and hasattr(buffer, "sample_rate"):
                        # Single AudioFrame
                        end_time = buffer.samples_per_channel / buffer.sample_rate
                except Exception as duration_error:
                    self._logger.warning(f"Could not calculate audio duration: {duration_error}")
                    end_time = 0.0
                return_data = stt.SpeechData(
                        language=opts_language,
                        text=transcript_text,
                        start_time=start_time,
                        end_time=end_time,
                        confidence=1.0,  # Hamsa doesn't provide confidence score
                    )
                return_data.gender = "Male"
                alternatives = [return_data

                ]
                
                return stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=alternatives,
                )

        except asyncio.TimeoutError as e:
            self._logger.error(f"Hamsa API timeout: {e}")
            raise APITimeoutError("Hamsa API request timed out") from e
        except aiohttp.ClientError as e:
            self._logger.error(f"Hamsa API client error: {e}")
            raise APIConnectionError(f"Hamsa API connection error: {e}") from e
        except Exception as e:
            self._logger.error(f"Error during Hamsa STT processing: {e}")
            raise APIConnectionError(f"Unexpected error in Hamsa STT: {e}") from e

    async def aclose(self) -> None:
        """Clean up resources."""
        if self._session:
            await self._session.close()