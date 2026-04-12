"""
SKYMIRROR — Multi-Agent Traffic Camera Analysis System
======================================================
Processes traffic camera frames every 20 seconds through a LangGraph pipeline:

    VLM Agent → Validator → [Orchestrator/Router] → Expert Agents → Alert Manager

See `graph/graph.py` for the compiled LangGraph application.
"""

__version__ = "0.1.0"
