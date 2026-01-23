import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os
import tempfile

# Patch environment variables before importing main
os.environ["CHAOS_INTERVAL"] = "300"
os.environ["CHAOS_STARTUP_DELAY"] = "10"
os.environ["MEMORY_CHUNK_SIZE"] = "1000"  # Smaller for tests
os.environ["DISK_FILL_SIZE_MB"] = "1"  # Smaller for tests
os.environ["CPU_BURN_THREADS"] = "1"
os.environ["CPU_BURN_DURATION"] = "1"

from main import app, state, reset_state, fill_disk, cleanup_disk, DISK_JUNK_PATH


@pytest.fixture
def client():
    """Create a test client and reset state before each test."""
    reset_state()
    state["current_scenario"] = "TEST"
    state["request_count"] = 0
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clean_disk():
    """Ensure disk junk file is cleaned up after tests."""
    yield
    if os.path.exists(DISK_JUNK_PATH):
        os.remove(DISK_JUNK_PATH)


class TestHealthEndpoints:
    """Tests for Kubernetes probe endpoints."""

    def test_healthz_healthy(self, client):
        """GET /healthz returns 200 when healthy."""
        state["is_unhealthy"] = False
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "scenario" in data

    def test_healthz_unhealthy(self, client):
        """GET /healthz returns 500 when unhealthy."""
        state["is_unhealthy"] = True
        response = client.get("/healthz")
        assert response.status_code == 500
        assert response.text == "Unhealthy"

    def test_readyz_ready(self, client):
        """GET /readyz returns 200 when ready."""
        state["is_unhealthy"] = False
        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"

    def test_readyz_not_ready(self, client):
        """GET /readyz returns 503 when unhealthy."""
        state["is_unhealthy"] = True
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.text == "Not Ready"


class TestIndexEndpoint:
    """Tests for the main index endpoint."""

    def test_index_returns_html(self, client):
        """GET / returns HTML template."""
        state["request_count"] = 0  # Next will be 1, not divisible by 3
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "FastAPI Fastfail" in response.text

    def test_index_chaos_error_every_third_request(self, client):
        """GET / returns 500 on every 3rd request."""
        state["request_count"] = 2  # Next will be 3, divisible by 3
        response = client.get("/")
        assert response.status_code == 500
        assert response.text == "Chaos Error"

    def test_index_increments_request_count(self, client):
        """GET / increments request counter."""
        state["request_count"] = 0
        client.get("/")
        assert state["request_count"] == 1
        client.get("/")
        assert state["request_count"] == 2


class TestStatusEndpoint:
    """Tests for the status endpoint."""

    def test_status_returns_full_state(self, client):
        """GET /status returns complete state and config."""
        state["current_scenario"] = "TEST_SCENARIO"
        state["is_unhealthy"] = True
        state["request_count"] = 42

        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()

        assert data["current_scenario"] == "TEST_SCENARIO"
        assert data["is_unhealthy"] is True
        assert data["request_count"] == 42
        assert "memory_hoard_size_mb" in data
        assert "config" in data
        assert "chaos_interval" in data["config"]
        assert "cpu_burn_threads" in data["config"]


class TestChaosEndpoints:
    """Tests for chaos trigger endpoints."""

    def test_chaos_reset(self, client, clean_disk):
        """POST /chaos/reset resets the chaos state."""
        state["is_unhealthy"] = True
        state["memory_hoard"] = ["chunk1", "chunk2"]
        state["current_scenario"] = "OOM_KILL"

        response = client.post("/chaos/reset")
        assert response.status_code == 200
        data = response.json()

        assert data["message"] == "Chaos state reset"
        assert state["is_unhealthy"] is False
        assert state["memory_hoard"] == []
        assert state["current_scenario"] == "MANUAL_RESET"

    def test_chaos_cpu(self, client):
        """POST /chaos/cpu starts CPU burn threads."""
        response = client.post("/chaos/cpu")
        assert response.status_code == 200
        data = response.json()

        assert "Manual CPU spike started" in data["message"]
        assert state["current_scenario"] == "MANUAL_CPU"

    def test_chaos_oom(self, client):
        """POST /chaos/oom adds memory pressure."""
        initial_len = len(state["memory_hoard"])
        response = client.post("/chaos/oom")
        assert response.status_code == 200
        data = response.json()

        assert "Manual OOM pressure added" in data["message"]
        assert state["current_scenario"] == "MANUAL_OOM"
        assert len(state["memory_hoard"]) > initial_len

    def test_chaos_disk(self, client, clean_disk):
        """POST /chaos/disk starts disk fill."""
        response = client.post("/chaos/disk")
        assert response.status_code == 200
        data = response.json()

        assert data["message"] == "Disk fill started"
        assert state["current_scenario"] == "MANUAL_DISK_FILL"

    def test_chaos_unhealthy_toggle(self, client):
        """POST /chaos/unhealthy toggles health state."""
        state["is_unhealthy"] = False

        response = client.post("/chaos/unhealthy")
        assert response.status_code == 200
        assert response.json()["is_unhealthy"] is True
        assert state["is_unhealthy"] is True

        response = client.post("/chaos/unhealthy")
        assert response.status_code == 200
        assert response.json()["is_unhealthy"] is False
        assert state["is_unhealthy"] is False


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_reset_state_clears_all(self, clean_disk):
        """reset_state() clears unhealthy flag and memory."""
        state["is_unhealthy"] = True
        state["memory_hoard"] = ["chunk1", "chunk2", "chunk3"]

        reset_state()

        assert state["is_unhealthy"] is False
        assert state["memory_hoard"] == []

    def test_fill_disk_creates_file(self, clean_disk):
        """fill_disk() creates junk file."""
        fill_disk()
        assert os.path.exists(DISK_JUNK_PATH)
        # Check size (should be ~1MB based on test env var)
        size = os.path.getsize(DISK_JUNK_PATH)
        assert size > 0

    def test_cleanup_disk_removes_file(self, clean_disk):
        """cleanup_disk() removes junk file if exists."""
        # Create the file first
        fill_disk()
        assert os.path.exists(DISK_JUNK_PATH)

        # Clean it up
        cleanup_disk()
        assert not os.path.exists(DISK_JUNK_PATH)

    def test_cleanup_disk_handles_missing_file(self):
        """cleanup_disk() handles non-existent file gracefully."""
        if os.path.exists(DISK_JUNK_PATH):
            os.remove(DISK_JUNK_PATH)

        # Should not raise
        cleanup_disk()


class TestChaosScenarios:
    """Integration tests for chaos scenarios."""

    def test_slow_death_affects_both_probes(self, client):
        """SLOW_DEATH scenario makes both probes fail."""
        state["is_unhealthy"] = True
        state["current_scenario"] = "SLOW_DEATH"

        health_response = client.get("/healthz")
        ready_response = client.get("/readyz")

        assert health_response.status_code == 500
        assert ready_response.status_code == 503

    def test_stable_scenario_keeps_healthy(self, client):
        """STABLE scenario keeps probes healthy."""
        state["is_unhealthy"] = False
        state["current_scenario"] = "STABLE"

        health_response = client.get("/healthz")
        ready_response = client.get("/readyz")

        assert health_response.status_code == 200
        assert ready_response.status_code == 200
