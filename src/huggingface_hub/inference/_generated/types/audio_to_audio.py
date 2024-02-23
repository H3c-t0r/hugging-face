# Inference code generated from the JSON schema spec in @huggingface/tasks.
#
# Using ./src/scripts/inference-codegen
#
# See https://github.com/huggingface/huggingface.js/tree/main/packages/tasks/src/tasks.
from dataclasses import dataclass
from typing import Any

from .base import BaseInferenceType


@dataclass
class AudioToAudioInput(BaseInferenceType):
    """Inputs for Audio to Audio inference"""

    inputs: Any
    """The input audio data"""


@dataclass
class AudioToAudioOutputElement(BaseInferenceType):
    """Outputs of inference for the Audio To Audio task
    A generated audio file with its label.
    """

    blob: Any
    """The generated audio file."""
    content_type: str
    """The content type of audio file."""
    label: str
    """The label of the audio file."""
