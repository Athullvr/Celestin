"""Optional PageIndex-style document retrieval: heading trees plus LLM navigation.

SQLite stays Celestin's authoritative store for chat and decisions. This package
indexes long Markdown documents into section trees kept in a separate,
rebuildable SQLite file and lets an LLM pick relevant sections from the outline.
"""
