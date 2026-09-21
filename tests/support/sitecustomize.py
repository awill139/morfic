"""Test-only startup hook (put on PYTHONPATH by scripts/run_tests.py).

http.server.HTTPServer.server_bind() calls socket.getfqdn(), a reverse-DNS lookup. On some CI networks
(GitHub's macOS runners) that takes ~35 seconds, which makes every mock server in the tests slow and makes
the demo static app miss its 15 second startup check. Answering locally keeps the tests fast and
deterministic; it does not change what the tests verify.
"""
import socket

socket.getfqdn = lambda name="": name or "localhost"
