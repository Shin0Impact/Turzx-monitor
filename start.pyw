"""Starts the app without a console window (used by the Start Menu shortcut and Windows startup)."""
import sys

from turingscreen.launch import run

run(sys.argv[1:])
