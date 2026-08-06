from uuid import uuid4
from threading import Lock


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.lock = Lock()

    def create_job(self):
        job_id = str(uuid4())

        with self.lock:
            self.jobs[job_id] = {
                "status": "queued",
                "progress": 0,
                "story": None,
                "error": None,
            }

        return job_id

    def update(
        self,
        job_id,
        *,
        status=None,
        progress=None,
        story=None,
        error=None,
    ):
        with self.lock:

            if job_id not in self.jobs:
                return

            if status is not None:
                self.jobs[job_id]["status"] = status

            if progress is not None:
                self.jobs[job_id]["progress"] = progress

            if story is not None:
                self.jobs[job_id]["story"] = story

            if error is not None:
                self.jobs[job_id]["error"] = error

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)