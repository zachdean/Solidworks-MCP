"""Windows + real-SolidWorks integration suite (sw-17y.1).

Collected on every platform; every module here marks its tests
`@pytest.mark.windows` and skips off Windows (see `conftest.py`), so
`scripts/check.sh` stays green on macOS while still exercising the full
tool surface against real SolidWorks on a Windows run.
"""
