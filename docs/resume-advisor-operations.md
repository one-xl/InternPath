# Resume Advisor Operations

## Worker Topology

- `internpath-default` is consumed only by `backend.rq_worker --queues internpath-default`.
- `internpath-advisor` is consumed only by `backend.advisor_autoscaler --queue internpath-advisor` and the child workers it manages.
- `ADVISOR_AUTOSCALE_MIN_WORKERS`, `ADVISOR_AUTOSCALE_MAX_WORKERS`, and `ADVISOR_AUTOSCALE_JOBS_PER_WORKER` control the baseline, ceiling, and queue-depth target.

The autoscaler preserves the configured baseline and only retires workers reported idle by RQ. It never starts a worker that listens to the default queue.

## Event Delivery

PostgreSQL stores every Advisor event and remains the reconnect source of truth. After commit, the repository publishes only the event sequence to `internpath:resume-advisor:events:<session-id>`. SSE readers use Redis `XREAD BLOCK` to wait for a notification and then fetch the durable event by sequence. A Redis outage falls back to the SSE polling interval without discarding events.

Set `ADVISOR_EVENT_STREAM_MAXLEN`, `ADVISOR_EVENT_STREAM_BLOCK_MILLISECONDS`, and `ADVISOR_EVENT_STATUS_POLL_SECONDS` to tune notification retention, blocking reads, and terminal-status checks.

## SLO Dashboard

`GET /api/agent/resume/operations/slo?windowHours=24` reports the current user's queue, Provider first-token, and end-to-end first-token P95 values. The endpoint returns a warning alert when P95 reaches its configured target:

- `queueMs`: 1,000 ms
- `providerFirstTokenMs`: 8,000 ms
- `endToEndFirstTokenMs`: 10,000 ms

The Resume Advisor header displays the same 24-hour telemetry outside the conversation history. The underlying values are stored in `agent_resume_runs.telemetry_json` when the first real model delta is persisted.

## Reverse Proxy

Use [internpath.conf.example](../deploy/nginx/internpath.conf.example) as the Nginx starting point. The Advisor SSE location disables proxy buffering, caching, and gzip, and keeps the upstream read timeout open for the whole run.
