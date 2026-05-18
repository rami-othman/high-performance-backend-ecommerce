# Task 5 - Load Distribution

## 1. Requirement

Simulate distributing incoming requests across more than one server and explain the distribution strategy used.

## 2. Problem Being Solved

A single Django backend container can become a bottleneck when request traffic increases. Task 5 demonstrates horizontal request distribution without changing the project into microservices and without creating separate databases or Redis instances.

## 3. Architecture

The project runs three identical Django web containers behind HAProxy:

- `web` identifies itself as `web-1`
- `web2` identifies itself as `web-2`
- `web3` identifies itself as `web-3`

All three containers run the same monolithic Django code and connect to the same PostgreSQL and Redis services.

## 4. Load Balancing Flow

```text
Client
 -> HAProxy Load Balancer
 -> Round Robin selection
 -> web-1 / web-2 / web-3
 -> shared PostgreSQL
 -> shared Redis
```

The public entrypoint is:

```text
http://localhost:8000
```

That host port maps to HAProxy. The Django containers expose port `8000` only inside the Docker network.

## 5. Why Round Robin Was Selected

Round Robin was selected because all backend containers are homogeneous:

- Same Django image
- Same codebase
- Same database and Redis services
- Same Gunicorn worker/thread settings
- Similar short API request workload

The lecture guidance says Round Robin is suitable when servers have similar hardware and tasks take roughly similar time.

## 6. Why Least Connections Was Not Selected

Least Connections is useful when requests are long-lived or have highly variable duration. The current proof uses short `/api/server-info/` requests and similar API workloads, so active connection count is not the main differentiator.

Round Robin is simpler and easier to prove for this simulation.

## 7. Why IP Hash / Sticky Sessions Were Not Selected

Sticky sessions are unnecessary because the project does not store user login state inside one web container.

The system uses:

- JWT tokens sent with each request
- shared PostgreSQL for users, carts, orders, payments, and reports
- shared Redis for capacity control and queue/cache infrastructure

Any backend container can handle any request, so pinning a client to one server would reduce distribution without adding correctness.

## 8. Why Weighted Round Robin Was Not Selected

Weighted Round Robin is useful when servers have different capacity. In this simulation, `web`, `web2`, and `web3` are equal containers with the same image and settings. No container has more CPU or RAM assigned than another, so equal Round Robin weights are appropriate.

## 9. Health Checks

HAProxy uses an L7 HTTP health check:

```text
GET /api/health/
```

The endpoint returns:

```json
{
  "status": "ok",
  "server_name": "web-1",
  "hostname": "container-hostname",
  "timestamp": "2026-05-18T..."
}
```

HAProxy removes unhealthy servers from rotation when health checks fail and adds them back after successful checks.

## 10. Stateless Architecture

The web layer is stateless enough for load balancing:

- JWT auth is validated by any backend using the shared Django secret.
- Persistent business data is in PostgreSQL.
- Redis is shared for checkout capacity control, cache configuration, and Celery broker/result backend.
- Celery workers are separate from the request-serving web containers.

Task 1 remains safe because PostgreSQL row-level locks protect stock even when requests arrive through different web containers. Task 2 remains global because the checkout capacity counter is in shared Redis.

## 11. Proof Script

The proof script is:

```bash
python scripts/load_distribution_test.py
```

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/load_distribution_test.py
```

Host machine:

```bash
python scripts/load_distribution_test.py
```

The script:

1. Waits for `/api/health/` through HAProxy.
2. Sends 60 requests by default to `/api/server-info/`.
3. Uses `Connection: close` so persistent connections do not hide Round Robin behavior.
4. Counts `server_name` values and `X-Backend-Server` headers.
5. Verifies all expected backends are reached.
6. Saves JSON proof results under `results/load_distribution/`.

## 12. Expected Output

```text
Task 5 - Load Distribution Proof

Load balancer URL: http://load_balancer
Strategy: Round Robin
Total requests: 60
Successful responses: 60
Failed responses: 0

Backend distribution:
- web-1: about 20 requests
- web-2: about 20 requests
- web-3: about 20 requests

Unique backend servers reached: 3
All expected servers reached: Yes
Distribution reasonably balanced: Yes
Health endpoint available: Yes
Result: PASSED
```

## 13. Limitations And Future Improvements

- Real cloud auto-scaling.
- Container orchestration with Kubernetes.
- Monitoring dashboards.
- Production TLS termination.
- Advanced algorithms for uneven workloads.
- Authenticated HAProxy stats in production.
