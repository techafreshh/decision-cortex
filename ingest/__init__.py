"""Data pipeline for the Decision Cortex corpus.

Snapshot acquisition, parsing, and the Phase-1 FalkorDB loader live here. The
parsers and the payload builder are dependency-free; the loader
(:mod:`ingest.graph`) imports GraphRAG-SDK lazily and makes no LLM call.
"""
