"""Entry point: python -m gui"""
# NiceGUI requires page definitions to exist before ui.run(),
# and this module must not use an `if __name__` guard.
import gui.app  # noqa: F401 — registers @ui.page routes
from nicegui import ui

ui.run(
    title="LLUPS Experiment Manager",
    port=8080,
    reload=False,
    show=True,
)
