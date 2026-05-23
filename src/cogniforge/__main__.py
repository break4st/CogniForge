"""Main entry point for CogniForge"""

import sys

# Force UTF-8 encoding on all stdio streams (Windows compatibility)
if sys.platform == "win32":
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

from cogniforge.cli import cli

if __name__ == "__main__":
    cli()
