"""Synthetic agent for operator-boundary tests. Not a test module. Standard library only.

  boundary_agent.py runner <base> <out> <go>  stand-in runner: waits for <go>, then starts a
                                              worker that detaches (double fork, no setsid)
  boundary_agent.py worker <base> <out>       forks; the orphaned grandchild makes the calls
  boundary_agent.py direct <base> <out>       makes the calls itself (configured executable)

Every call carries the inherited environment plus forged operator material: a session
cookie, a bearer token, the guard header and a recovery token. Results go to <out> as JSON.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

CALLS = [
    ("approve", "POST", "/api/cards/1/approve", {}),
    ("create_card", "POST", "/api/cards", {"title": "agent-made", "agent": "claude"}),
    ("resume_project", "POST", "/api/projects/1/resume", {}),
    ("github_settings", "PUT", "/api/github/config", {"enabled": True}),
    ("report_settings", "PUT", "/api/report-storage", {}),
    ("recover", "POST", "/auth/recover", {"token": os.environ.get("FORGED_RECOVERY_TOKEN", "x" * 64)}),
    ("read_cards", "GET", "/api/cards", None),
    ("health", "GET", "/healthz", None),
]


def call(base, method, path, body, bearer=False):
    headers = {"X-Mac-Control": "1", "Cookie": "mcd_session=" + os.environ.get("FORGED_SESSION", "forged"),
               "Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + "A" * 64
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=20) as response:
            return [response.status, response.read(2000).decode("utf-8", "replace")]
    except urllib.error.HTTPError as exc:
        return [exc.code, exc.read(2000).decode("utf-8", "replace")]


def make_calls(base, out):
    results = {name: call(base, method, path, body) for name, method, path, body in CALLS}
    results["bearer_cards"] = call(base, "GET", "/api/cards", None, bearer=True)
    results["_pid"] = os.getpid()
    temporary = out + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(results, stream)
    os.replace(temporary, out)


def wait_for(path, seconds=60):
    deadline = time.monotonic() + seconds
    while not os.path.exists(path):
        if time.monotonic() > deadline:
            sys.exit(3)
        time.sleep(0.05)


def main(argv):
    mode, base, out = argv[1], argv[2], argv[3]
    if mode == "runner":
        wait_for(argv[4])
        subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "worker", base, out], check=False)
        wait_for(out)  # the runner stays alive while its detached descendant works
    elif mode == "worker":
        parent = os.getpid()
        if os.fork():
            os._exit(0)
        deadline = time.monotonic() + 10
        while os.getppid() == parent and time.monotonic() < deadline:
            time.sleep(0.02)
        make_calls(base, out)
        os._exit(0)
    elif mode == "direct":
        time.sleep(float(os.environ.get("AGENT_DELAY_S", "0")))
        make_calls(base, out)


if __name__ == "__main__":
    main(sys.argv)
