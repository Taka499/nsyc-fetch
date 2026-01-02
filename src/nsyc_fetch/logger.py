"""Structured logging for NSYC-Fetch runs.

Uses a global singleton pattern for easy access without parameter passing.
Initialize with init_logger() at the start of a run, then use get_logger()
anywhere in the codebase.
"""

import inspect
import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Global logger instance
_logger: "RunLogger | None" = None


def init_logger(base_dir: str = "logs") -> "RunLogger":
    """Initialize the global logger for a new run.

    Args:
        base_dir: Base directory for all logs (default: "logs")

    Returns:
        The initialized RunLogger instance
    """
    global _logger
    _logger = RunLogger(base_dir)
    return _logger


def get_logger() -> "RunLogger | None":
    """Get the current global logger instance.

    Returns:
        The RunLogger instance, or None if not initialized
    """
    return _logger


def close_logger() -> None:
    """Close the logger and write summary."""
    global _logger
    if _logger:
        _logger.write_summary()
        _logger = None


class RunLogger:
    """Logger that captures fetch and extraction data for debugging.

    Creates a timestamped directory for each run containing:
    - Fetched content per source
    - LLM requests and responses
    - Extracted events
    - Run summary
    """

    def __init__(self, base_dir: str = "logs"):
        """Initialize logger with timestamped run directory.

        Args:
            base_dir: Base directory for all logs (default: "logs")
        """
        self.base_dir = Path(base_dir)
        self.start_time = datetime.now()
        timestamp = self.start_time.strftime("%Y-%m-%dT%H-%M-%S")
        self._run_dir = self.base_dir / timestamp
        self._run_dir.mkdir(parents=True, exist_ok=True)

        # Track stats for summary
        self._sources_processed = 0
        self._events_extracted = 0
        self._errors: list[str] = []

    @property
    def run_dir(self) -> Path:
        """Return the current run's log directory."""
        return self._run_dir

    def _source_dir(self, source_id: str) -> Path:
        """Get or create directory for a source."""
        source_dir = self._run_dir / source_id
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    def _write_json(self, path: Path, data: Any) -> None:
        """Write data to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    def _get_caller_info(self) -> dict[str, Any]:
        """Get information about the calling function."""
        # Go up the stack to find the actual caller (skip internal methods)
        frame = inspect.currentframe()
        try:
            # Skip: _get_caller_info -> log_* method -> actual caller
            caller_frame = frame.f_back.f_back
            return {
                "function": caller_frame.f_code.co_name,
                "filename": Path(caller_frame.f_code.co_filename).name,
                "line": caller_frame.f_lineno,
            }
        finally:
            del frame

    def log_fetch(
        self,
        source_id: str,
        url: str,
        sections: list[str],
        combined_content: str,
        content_hash: str,
        detail_pages_fetched: int = 0,
    ) -> None:
        """Log fetched content for a source."""
        source_dir = self._source_dir(source_id)
        self._write_json(
            source_dir / "fetched_content.json",
            {
                "source_id": source_id,
                "url": url,
                "fetched_at": datetime.now().isoformat(),
                "content_hash": content_hash,
                "detail_pages_fetched": detail_pages_fetched,
                "num_sections": len(sections),
                "combined_content_length": len(combined_content),
                "caller": self._get_caller_info(),
                "sections": sections,
                "combined_content": combined_content,
            },
        )
        self._sources_processed += 1

    def log_llm_request(
        self,
        source_id: str,
        prompt: str,
        model: str,
        artist_name: str,
        page_index: int | None = None,
    ) -> None:
        """Log the prompt sent to LLM.

        Args:
            source_id: Source identifier
            prompt: The prompt sent to the LLM
            model: Model name used
            artist_name: Artist being processed
            page_index: Optional page index for per-page extraction logging.
                        If provided, creates llm_request_{index}.json instead of llm_request.json
        """
        source_dir = self._source_dir(source_id)
        filename = (
            f"llm_request_{page_index}.json"
            if page_index is not None
            else "llm_request.json"
        )
        self._write_json(
            source_dir / filename,
            {
                "source_id": source_id,
                "artist_name": artist_name,
                "model": model,
                "page_index": page_index,
                "timestamp": datetime.now().isoformat(),
                "prompt_length": len(prompt),
                "caller": self._get_caller_info(),
                "prompt": prompt,
            },
        )

    def log_llm_response(
        self,
        source_id: str,
        response: str,
        tokens_used: dict[str, int] | None = None,
        success: bool = True,
        error: str | None = None,
        page_index: int | None = None,
    ) -> None:
        """Log the raw LLM response.

        Args:
            source_id: Source identifier
            response: The raw response from the LLM
            tokens_used: Token usage statistics
            success: Whether the call succeeded
            error: Error message if failed
            page_index: Optional page index for per-page extraction logging.
                        If provided, creates llm_response_{index}.json instead of llm_response.json
        """
        source_dir = self._source_dir(source_id)
        filename = (
            f"llm_response_{page_index}.json"
            if page_index is not None
            else "llm_response.json"
        )
        self._write_json(
            source_dir / filename,
            {
                "source_id": source_id,
                "page_index": page_index,
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "error": error,
                "response_length": len(response),
                "tokens_used": tokens_used,
                "caller": self._get_caller_info(),
                "response": response,
            },
        )
        if error:
            self._errors.append(f"{source_id}: {error}")

    def log_events(
        self,
        source_id: str,
        events: list[dict[str, Any]],
        page_index: int | None = None,
    ) -> None:
        """Log extracted events.

        Args:
            source_id: Source identifier
            events: List of extracted events as dicts
            page_index: Optional page index for per-page extraction logging.
                        If provided, creates extracted_events_{index}.json
        """
        source_dir = self._source_dir(source_id)
        filename = (
            f"extracted_events_{page_index}.json"
            if page_index is not None
            else "extracted_events.json"
        )
        self._write_json(
            source_dir / filename,
            {
                "source_id": source_id,
                "page_index": page_index,
                "timestamp": datetime.now().isoformat(),
                "num_events": len(events),
                "caller": self._get_caller_info(),
                "events": events,
            },
        )
        self._events_extracted += len(events)

    def log_skip(self, source_id: str, reason: str) -> None:
        """Log when a source is skipped."""
        source_dir = self._source_dir(source_id)
        self._write_json(
            source_dir / "skipped.json",
            {
                "source_id": source_id,
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
                "caller": self._get_caller_info(),
            },
        )

    def log_error(self, source_id: str, error: str, context: str = "") -> None:
        """Log an error during processing."""
        source_dir = self._source_dir(source_id)
        self._write_json(
            source_dir / "error.json",
            {
                "source_id": source_id,
                "timestamp": datetime.now().isoformat(),
                "error": error,
                "context": context,
                "caller": self._get_caller_info(),
            },
        )
        self._errors.append(f"{source_id}: {error}")

    def write_summary(self) -> None:
        """Write run summary with metadata and stats."""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()
        self._write_json(
            self._run_dir / "run_summary.json",
            {
                "start_time": self.start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "sources_processed": self._sources_processed,
                "events_extracted": self._events_extracted,
                "errors": self._errors,
                "log_directory": str(self._run_dir),
            },
        )
