"""Unit tests for Stage A async predict jobs (Task T18)."""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from predictor import jobs
from predictor.api import app
from predictor.jobs import JobStore


def _fake_predict(query, context=None, *, on_progress=None):
    if on_progress:
        on_progress("interpret", 10, "Interpreting…", None)
        on_progress("evidence", 50, "Verifying…", {"claim_index": 0})
        on_progress("done", 100, "Complete", None)
    return {
        "input": query,
        "status": "recommendation",
        "outcome": {"formula": "Test Formula"},
        "f_context": {},
        "disclaimer": "test",
    }


def _slow_predict(query, context=None, *, on_progress=None):
    time.sleep(2.5)
    return {"input": query, "status": "insufficient_evidence"}


class AsyncJobApiTests(unittest.TestCase):
    def setUp(self):
        self.store = JobStore(
            max_workers=2, default_timeout_s=30, retention_s=60
        )
        self._patcher = patch("predictor.api.jobs.STORE", self.store)
        self._patcher.start()
        self.client = TestClient(app)

    def tearDown(self):
        self._patcher.stop()
        self.store._executor.shutdown(wait=False, cancel_futures=True)

    def test_health_reports_async_jobs(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("async_jobs"))
        self.assertIn("predict_job_timeout_s", body)

    def test_sync_predict_still_works(self):
        with patch("predictor.api.pipeline.predict", side_effect=_fake_predict):
            r = self.client.post("/predict", json={"query": "stress"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "recommendation")

    def test_submit_and_poll_to_result(self):
        rec = self.store.submit_predict(
            query="stress", runner=_fake_predict
        )
        # Wait for completion
        deadline = time.time() + 5
        while time.time() < deadline:
            cur = self.store.get(rec.job_id)
            if cur and cur.status in ("succeeded", "failed", "timed_out"):
                break
            time.sleep(0.05)
        cur = self.store.get(rec.job_id)
        self.assertEqual(cur.status, "succeeded")
        self.assertEqual(cur.result["outcome"]["formula"], "Test Formula")
        self.assertEqual(cur.progress_percent, 100)

        r = self.client.get(f"/jobs/{rec.job_id}")
        self.assertEqual(r.status_code, 200)
        view = r.json()
        self.assertEqual(view["status"], "succeeded")
        self.assertIn("progress", view)
        self.assertEqual(view["progress"]["stage"], "done")
        self.assertEqual(view["result"]["input"], "stress")

        rr = self.client.get(f"/jobs/{rec.job_id}/result")
        self.assertEqual(rr.status_code, 200)
        self.assertEqual(rr.json()["status"], "recommendation")

    def test_http_submit_returns_202(self):
        with patch("predictor.pipeline.predict", side_effect=_fake_predict):
            r = self.client.post("/jobs/predict", json={"query": "knee pain"})
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertIn("job_id", body)
        self.assertIn(body["status"], ("queued", "running", "succeeded"))
        self.assertTrue(body["poll_url"].startswith("/jobs/"))
        # Poll until done
        job_id = body["job_id"]
        deadline = time.time() + 5
        final = None
        while time.time() < deadline:
            pr = self.client.get(f"/jobs/{job_id}")
            final = pr.json()
            if final["status"] in ("succeeded", "failed", "timed_out"):
                break
            time.sleep(0.05)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["result"]["input"], "knee pain")

    def test_idempotent_retry_returns_same_job(self):
        with patch("predictor.pipeline.predict", side_effect=_fake_predict):
            h = {"Idempotency-Key": "demo-key-1"}
            a = self.client.post(
                "/jobs/predict", json={"query": "same"}, headers=h
            )
            b = self.client.post(
                "/jobs/predict", json={"query": "same"}, headers=h
            )
        self.assertEqual(a.status_code, 202)
        self.assertEqual(b.status_code, 202)
        self.assertEqual(a.json()["job_id"], b.json()["job_id"])

    def test_unknown_job_404(self):
        r = self.client.get("/jobs/does-not-exist")
        self.assertEqual(r.status_code, 404)

    def test_result_while_running_is_409(self):
        gate = {"go": False}

        def blocked(query, context=None, *, on_progress=None):
            while not gate["go"]:
                time.sleep(0.02)
            return {"input": query, "status": "recommendation"}

        with patch("predictor.pipeline.predict", side_effect=blocked):
            r = self.client.post("/jobs/predict", json={"query": "wait"})
            job_id = r.json()["job_id"]
            # Give worker a moment to start
            time.sleep(0.1)
            mid = self.client.get(f"/jobs/{job_id}/result")
            self.assertEqual(mid.status_code, 409)
            gate["go"] = True
            deadline = time.time() + 5
            while time.time() < deadline:
                if self.store.get(job_id).status == "succeeded":
                    break
                time.sleep(0.05)

    def test_timeout_marks_timed_out(self):
        tiny = JobStore(max_workers=1, default_timeout_s=0.3, retention_s=60)
        try:
            rec = tiny.submit_predict(query="slow", runner=_slow_predict, timeout_s=0.3)
            deadline = time.time() + 5
            while time.time() < deadline:
                cur = tiny.get(rec.job_id)
                if cur.status in ("timed_out", "failed", "succeeded"):
                    break
                time.sleep(0.05)
            cur = tiny.get(rec.job_id)
            self.assertEqual(cur.status, "timed_out")
            self.assertIn("budget", (cur.error or "").lower())
        finally:
            tiny._executor.shutdown(wait=False, cancel_futures=True)


class JobStoreUnitTests(unittest.TestCase):
    def test_progress_fields_in_public_view(self):
        store = JobStore(max_workers=1, default_timeout_s=10, retention_s=30)
        try:
            rec = store.submit_predict(query="x", runner=_fake_predict)
            deadline = time.time() + 3
            while time.time() < deadline:
                if store.get(rec.job_id).status == "succeeded":
                    break
                time.sleep(0.05)
            view = store.public_view(store.get(rec.job_id))
            self.assertEqual(view["progress"]["percent"], 100)
            self.assertEqual(view["kind"], "predict")
        finally:
            store._executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
