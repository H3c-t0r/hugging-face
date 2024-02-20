# Inference code generated from the JSON schema spec in ./spec
#
# Using src/scripts/inference-codegen
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseInferenceType


@dataclass
class SentenceSimilarityInputData(BaseInferenceType):
    sentences: List[str]
    """A list of strings which will be compared against the source_sentence."""
    source_sentence: str
    """The string that you wish to compare the other strings with. This can be a phrase,
    sentence, or longer passage, depending on the model being used.
    """


@dataclass
class SentenceSimilarityInput(BaseInferenceType):
    """Inputs for Sentence similarity inference"""

    inputs: SentenceSimilarityInputData
    parameters: Optional[Dict[str, Any]] = None
    """Additional inference parameters"""
