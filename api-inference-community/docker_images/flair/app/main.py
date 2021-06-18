import logging
import os
import functools
from typing import Dict, Type

from api_inference_community.routes import pipeline_route, status_ok
from app.pipelines import Pipeline, TokenClassificationPipeline
from starlette.applications import Starlette
from starlette.routing import Route


logger = logging.getLogger(__name__)

# Add the allowed tasks
# Supported tasks are:
# - text-generation
# - text-classification
# - token-classification
# - translation
# - summarization
# - automatic-speech-recognition
# - ...
# For instance
# from app.pipelines import AutomaticSpeechRecognitionPipeline
# ALLOWED_TASKS = {"automatic-speech-recognition": AutomaticSpeechRecognitionPipeline}
# You can check the requirements and expectations of each pipelines in their respective
# directories. Implement directly within the directories.
ALLOWED_TASKS: Dict[str, Type[Pipeline]] = {
    "token-classification": TokenClassificationPipeline
}


@functools.lru_cache()
def get_pipeline() -> Pipeline:
    task = os.environ["TASK"]
    model_id = os.environ["MODEL_ID"]
    if task not in ALLOWED_TASKS:
        raise EnvironmentError(f"{task} is not a valid pipeline for model : {model_id}")
    return ALLOWED_TASKS[task](model_id)


routes = [
    Route("/{whatever:path}", status_ok),
    Route("/{whatever:path}", pipeline_route, methods=["POST"]),
]

app = Starlette(routes=routes)
if os.environ.get("DEBUG", "") == "1":
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_headers=["*"], allow_methods=["*"]
    )


@app.on_event("startup")
async def startup_event():
    logger = logging.getLogger("uvicorn.access")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.handlers = [handler]

    app.get_pipeline = get_pipeline


if __name__ == "__main__":
    try:
        get_pipeline()
    except Exception:
        # We can fail so we can show exception later.
        pass
