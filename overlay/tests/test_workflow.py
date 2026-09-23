from __future__ import annotations

import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "follow-upstream.yml"
DISABLE_AFTER_DAYS = 60  # GitHub disables idle scheduled workflows in public repositories
MIN_KEEPALIVE_ATTEMPTS = 4  # weekly runs between the keepalive threshold and the cutoff


def jobs(text: str) -> dict[str, str]:
    """Each top-level job's block of the workflow, keyed by job id."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z0-9_-]+):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def steps(job: str) -> dict[str, str]:
    """Each step's block within a job, keyed by step name."""
    parts = re.split(r"^      - name: (.+)\n", job, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.jobs = jobs(WORKFLOW.read_text())

    def test_keepalive_is_its_own_job_that_waits_on_nothing(self):
        self.assertIn("keepalive", self.jobs)
        self.assertNotIn("needs:", self.jobs["keepalive"])
        self.assertNotIn(".keepalive", self.jobs["check"])

    def test_build_waits_only_on_check(self):
        needs = re.findall(r"^    needs: (.+)$", self.jobs["build"], flags=re.MULTILINE)
        self.assertEqual(needs, ["check"])

    def test_keepalive_threshold_leaves_several_weekly_attempts(self):
        days = int(re.search(r'"\$age_days" -ge (\d+)', self.jobs["keepalive"]).group(1))
        self.assertGreaterEqual((DISABLE_AFTER_DAYS - days) // 7, MIN_KEEPALIVE_ATTEMPTS)

    def test_write_token_reaches_only_the_publish_step_of_the_build(self):
        build = self.jobs["build"]
        job_env = build.split("    steps:\n", 1)[0]
        self.assertNotIn("GH_TOKEN", job_env)
        holders = [name for name, block in steps(build).items() if "GH_TOKEN" in block]
        self.assertEqual(holders, ["Publish"])


if __name__ == "__main__":
    unittest.main()
