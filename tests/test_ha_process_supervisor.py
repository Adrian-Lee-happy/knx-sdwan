import sys
from pathlib import Path as _Path
sys.path.insert(0,str(_Path(__file__).resolve().parents[1]/'src/ha_node'))
import signal
import subprocess
import unittest
from process_supervisor import run_service


class ProcessTests(unittest.TestCase):
    def test_stop_signal_is_forwarded_and_handlers_restored(self):
        original=signal.getsignal(signal.SIGTERM)
        class Child:
            terminated=False
            def poll(self):return None
            def terminate(self):self.terminated=True
            def wait(self):
                signal.raise_signal(signal.SIGTERM)
                return 0
        child=Child()
        self.assertEqual(run_service(['fixture'],lambda argv:child),0)
        self.assertTrue(child.terminated)
        self.assertEqual(signal.getsignal(signal.SIGTERM),original)

    def test_unexpected_crash_is_not_treated_as_success(self):
        class Child:
            def wait(self):return 1
        with self.assertRaises(subprocess.CalledProcessError):
            run_service(['fixture'],lambda argv:Child())


if __name__=='__main__':unittest.main()
