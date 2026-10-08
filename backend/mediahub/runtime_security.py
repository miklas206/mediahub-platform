"""Process-local dump protection; does not change host-wide security settings."""

import os
import sys


def protect_process_memory():
    if os.name != "posix":
        return  # Windows is supported for development; Linux is the deployment target.
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        import ctypes

        # PR_SET_DUMPABLE=0 also restricts access to this process's sensitive memory.
        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
            raise RuntimeError("Process memory protection could not be applied")
