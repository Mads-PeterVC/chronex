"""Started by `chronex run`: records the Python process it is loaded into (zero-touch mode).

`chronex run` puts this directory first on PYTHONPATH and sets CHRONEX_AUTO, so any Python
process it launches, directly or through a shell script, records itself.
"""

import os

if os.environ.get("CHRONEX_AUTO") == "1":
    try:
        from chronex.runner import process

        process.start()
    except ImportError:  # chronex is not installed in this interpreter
        pass
