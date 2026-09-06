import subprocess
import sys

from faults import DUPLICATE_RESULT, PROCESS_CRASH, TOOL_TIMEOUT, FaultSpec


def test_process_crash_has_real_process_boundary_evidence() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    handle = PROCESS_CRASH.arm(process, FaultSpec("PROCESS_CRASH"))
    try:
        handle.trigger()
        assert PROCESS_CRASH.verify_triggered(handle.evidence, FaultSpec("PROCESS_CRASH"))
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()


def test_tool_timeout_uses_subprocess_executor_boundary() -> None:
    spec = FaultSpec("TOOL_TIMEOUT", parameters={"timeout_seconds": 0.03})
    handle = TOOL_TIMEOUT.arm(None, spec)
    assert handle.trigger([sys.executable, "-c", "import time; time.sleep(.3)"]) is None
    assert TOOL_TIMEOUT.verify_triggered(handle.evidence, spec)


def test_duplicate_result_delivers_same_result_twice() -> None:
    delivered = []
    spec = FaultSpec("DUPLICATE_RESULT")
    handle = DUPLICATE_RESULT.arm(delivered.append, spec)
    value = {"result": 1}
    handle.trigger(value)
    assert delivered == [value, value]
    assert delivered[0] is delivered[1]
    assert DUPLICATE_RESULT.verify_triggered(handle.evidence, spec)
