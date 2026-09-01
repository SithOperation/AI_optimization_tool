import os
import sys

# PyInstaller's Windows GUI bootloader intentionally provides no console
# streams. Uvicorn inspects these streams while configuring logging, so give
# it safe sinks without creating a visible terminal window.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import uvicorn
from tokenscope_api.main import app

if __name__ == "__main__":
    os.environ.setdefault("AIOPT_RUNTIME", "desktop")
    # StatsForecast/Numba can run on its bundled workqueue. TBB is optional and
    # is intentionally not shipped until its runtime DLL can be signed/bundled.
    os.environ.setdefault("NUMBA_THREADING_LAYER", "workqueue")
    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
