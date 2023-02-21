import unittest
from unittest.mock import Mock, patch

from huggingface_hub.utils._telemetry import send_telemetry, _TELEMETRY_QUEUE

from .testing_constants import ENDPOINT_STAGING
from queue import Queue


@patch("huggingface_hub.utils._telemetry.requests.head")
@patch("huggingface_hub.utils._telemetry._TELEMETRY_QUEUE", new_callable=Queue)
@patch("huggingface_hub.utils._telemetry._TELEMETRY_THREAD", None)
class TestSendTelemetry(unittest.TestCase):
    def test_topic_normal(self, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="examples")
        queue.join()  # Wait for the telemetry tasks to be completed
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args[0][0], f"{ENDPOINT_STAGING}/api/telemetry/examples")

    def test_topic_multiple(self, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="example1")
        send_telemetry(topic="example2")
        send_telemetry(topic="example3")
        queue.join()  # Wait for the telemetry tasks to be completed

        self.assertEqual(mock_request.call_count, 3)  # 3 calls and order is preserved
        self.assertEqual(mock_request.call_args_list[0][0][0], f"{ENDPOINT_STAGING}/api/telemetry/example1")
        self.assertEqual(mock_request.call_args_list[1][0][0], f"{ENDPOINT_STAGING}/api/telemetry/example2")
        self.assertEqual(mock_request.call_args_list[2][0][0], f"{ENDPOINT_STAGING}/api/telemetry/example3")

    def test_topic_with_subtopic(self, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="gradio/image/this_one")
        queue.join()  # Wait for the telemetry tasks to be completed
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args[0][0], f"{ENDPOINT_STAGING}/api/telemetry/gradio/image/this_one")

    def test_topic_quoted(self, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="foo bar")
        queue.join()  # Wait for the telemetry tasks to be completed
        mock_request.assert_called_once()
        self.assertEqual(mock_request.call_args[0][0], f"{ENDPOINT_STAGING}/api/telemetry/foo%20bar")

    @patch("huggingface_hub.utils._telemetry.constants.HF_HUB_OFFLINE", True)
    def test_hub_offline(self, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="topic")
        self.assertTrue(queue.empty())  # no tasks
        mock_request.assert_not_called()

    @patch("huggingface_hub.utils._telemetry.constants.HF_HUB_DISABLE_TELEMETRY", True)
    def test_telemetry_disabled(self, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="topic")
        self.assertTrue(queue.empty())  # no tasks
        mock_request.assert_not_called()

    @patch("huggingface_hub.utils._telemetry.build_hf_headers")
    def test_telemetry_use_build_hf_headers(self, mock_headers: Mock, queue: Queue, mock_request: Mock) -> None:
        send_telemetry(topic="topic")
        queue.join()  # Wait for the telemetry tasks to be completed
        mock_request.assert_called_once()
        mock_headers.assert_called_once()
        self.assertEqual(mock_request.call_args[1]["headers"], mock_headers.return_value)


@patch("huggingface_hub.utils._telemetry.requests.head", side_effect=Exception("whatever"))
@patch("huggingface_hub.utils._telemetry._TELEMETRY_QUEUE", new_callable=Queue)
@patch("huggingface_hub.utils._telemetry._TELEMETRY_THREAD", None)
class TestSendTelemetryConnectionError(unittest.TestCase):
    def test_telemetry_exception_silenced(self, queue: Queue, mock_request: Mock) -> None:
        with self.assertLogs(logger="huggingface_hub.utils._telemetry", level="DEBUG") as captured:
            send_telemetry(topic="topic")
            queue.join()

        # Assert debug message with traceback for debug purposes
        self.assertEqual(len(captured.output), 1)
        self.assertEqual(
            captured.output[0],
            "DEBUG:huggingface_hub.utils._telemetry:Error while sending telemetry: whatever",
        )
