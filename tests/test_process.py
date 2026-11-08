from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from publisher_engine.process import run_process
import publisher_engine.process as process_module


class BoundedProcessTests(unittest.TestCase):
    def test_large_stdout_and_stderr_are_drained_but_only_tails_retained(self):
        script = (
            "import sys; "
            "sys.stdout.buffer.write(b'O' * (12 * 1024 * 1024)); "
            "sys.stdout.flush(); "
            "sys.stderr.buffer.write(b'E' * (12 * 1024 * 1024)); "
            "sys.stderr.flush()"
        )
        result = run_process([sys.executable, "-c", script], timeout=20,
                             max_output_bytes=4096)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "O" * 4096)
        self.assertEqual(result.stderr, "E" * 4096)

    def test_zero_retention_still_drains_pipes_and_completes(self):
        script = "import sys; sys.stdout.write('x' * 1000000); sys.stderr.write('y' * 1000000)"
        result = run_process([sys.executable, "-c", script], timeout=10,
                             max_output_bytes=0)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_timeout_contains_only_bounded_tail(self):
        script = "import sys,time; print('A' * 10000, flush=True); time.sleep(20)"
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            run_process([sys.executable, "-c", script], timeout=2.0,
                        max_output_bytes=512)
        output = caught.exception.stdout or caught.exception.output or ""
        self.assertLessEqual(len(output.encode("utf-8")), 512)
        self.assertIn("A", output)

    def test_timeout_closes_captured_pipe_handles(self):
        captured = []
        real_popen = subprocess.Popen

        def recording_popen(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            captured.append(child)
            return child

        with mock.patch.object(process_module.subprocess, "Popen", side_effect=recording_popen):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_process([sys.executable, "-c", "import time; time.sleep(20)"],
                            timeout=0.25, max_output_bytes=128)

        self.assertEqual(len(captured), 1)
        self.assertIsNotNone(captured[0].stdout)
        self.assertTrue(captured[0].stdout.closed)
        self.assertIsNotNone(captured[0].stderr)
        self.assertTrue(captured[0].stderr.closed)

    @unittest.skipIf(os.name == "nt", "POSIX process-group behavior is verified on Linux")
    def test_timeout_kills_descendant_process_group(self):
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "child-survived.txt"
            child_code = (
                "import pathlib,time; time.sleep(1.4); "
                f"pathlib.Path({str(marker)!r}).write_text('survived')"
            )
            parent_code = (
                "import subprocess,sys,time; "
                "subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
                "time.sleep(20)"
            )
            with self.assertRaises(subprocess.TimeoutExpired):
                run_process([sys.executable, "-c", parent_code, child_code],
                            timeout=0.45, max_output_bytes=128)
            time.sleep(1.7)
            self.assertFalse(marker.exists(), "descendant remained alive after timeout cleanup")

    def test_stderr_can_be_merged_into_bounded_stdout(self):
        script = "import sys; sys.stdout.write('out'); sys.stderr.write('err')"
        result = run_process([sys.executable, "-c", script], timeout=5,
                             stderr_to_stdout=True, max_output_bytes=128)
        self.assertEqual(result.returncode, 0)
        self.assertCountEqual(result.stdout, "outerr")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
