"""Forward container stop signals and wait for the Agent's cleanup."""
import signal
import subprocess


def run_service(argv, popen=subprocess.Popen):
    child = None
    stopping = False
    previous = {}

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.terminate()

    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, stop)
        child = popen(argv)
        if stopping and child.poll() is None:
            child.terminate()
        code = child.wait()
        if code and not stopping:
            raise subprocess.CalledProcessError(code, argv)
        return code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
