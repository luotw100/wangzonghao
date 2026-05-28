"""Thin pywebview GUI over the existing command layer.

GUI mode reuses laborster_bridge.commands.DISPATCH and Events in the
same process; it never drives the REPL. CLI behaviour is unchanged.
"""
