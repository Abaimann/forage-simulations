"""Sink adapters writing pipeline artefacts to files or memory."""

from __future__ import annotations

from .file_sink import FileTelemetrySink
from .memory_sink import InMemoryTelemetrySink

__all__ = ["FileTelemetrySink", "InMemoryTelemetrySink"]
