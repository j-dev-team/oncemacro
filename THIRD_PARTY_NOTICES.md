# Third-party software

OnceMacro's own code is licensed under Apache-2.0 (see `LICENSE`).
The Windows build bundles the libraries below. Their licenses stay with them.

| Library | License |
|---|---|
| Qt for Python (PySide6, Shiboken6) and Qt | LGPL-3.0 |
| pynput | LGPL-3.0 |
| keyboard | MIT |
| PyAutoGUI and its helpers (PyScreeze, PyMsgBox, PyTweening, PyGetWindow, MouseInfo, pyperclip) | BSD-3-Clause |
| OpenCV (opencv-python) | Apache-2.0 |
| NumPy | BSD-3-Clause |
| mss | MIT |
| MCP Python SDK (mcp) and pydantic | MIT |
| pdfplumber, pdfminer.six | MIT |
| pypdfium2 / PDFium | Apache-2.0 / BSD-3-Clause |
| comtypes | MIT |
| pywin32 | PSF |
| Pillow | HPND (MIT-CMU) |

## LGPL libraries (Qt, PySide6, pynput)
The build is a folder build (not a single packed file): the LGPL libraries are separate files in `app\_internal\`
and are used unmodified. You may replace them with your own compatible builds. Their source code is available
from the projects: https://code.qt.io , https://github.com/moses-palmer/pynput .
