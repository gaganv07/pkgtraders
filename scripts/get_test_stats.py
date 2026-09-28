import pytest
import json
import time

class StatsPlugin:
    def pytest_terminal_summary(self, terminalreporter, exitstatus):
        stats = terminalreporter.stats
        passed = len(stats.get('passed', []))
        failed = len(stats.get('failed', []))
        errors = len(stats.get('error', []))
        skipped = len(stats.get('skipped', []))
        total = passed + failed + errors + skipped
        data = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "exitstatus": int(exitstatus),
        }
        with open("reports/test_suite_stats.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"TEST RUN COMPLETED: {passed}/{total} passed, {failed} failed, {errors} errors, {skipped} skipped.")

if __name__ == "__main__":
    t0 = time.time()
    plugin = StatsPlugin()
    pytest.main(["-q"], plugins=[plugin])
    print(f"Elapsed: {time.time() - t0:.2f}s")
