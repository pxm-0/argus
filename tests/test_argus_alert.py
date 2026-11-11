from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import argus_alert_sources as sources  # noqa: E402
import argus_alerting as alerting  # noqa: E402
import argus_cli  # noqa: E402


def load_script(name: str, module_name: str):
    loader = importlib.machinery.SourceFileLoader(module_name, str(ROOT / "scripts" / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


alert_script = load_script("argus-alert", "argus_alert_script")
poller = load_script("argus-alert-poller", "argus_alert_poller_script")

NOW = 1_800_000_000.0
HOUR, DAY = alerting.HOUR, alerting.DAY


def ids(findings):
    return [item["id"] for item in findings]


class Completed(SimpleNamespace):
    def __init__(self, stdout: str = "", returncode: int = 0):
        super().__init__(stdout=stdout, returncode=returncode, stderr="")


class BoundaryTest(unittest.TestCase):
    def test_smoke_is_stale_only_past_26_hours(self) -> None:
        at = lambda age: {"smokeLatest": {"ok": True, "timestamp": alerting.iso(NOW - age)}}
        self.assertEqual([], alerting.check_smoke(at(26 * HOUR), NOW))
        self.assertEqual(["smoke-stale"], ids(alerting.check_smoke(at(26 * HOUR + 1), NOW)))

    def test_failed_smoke_pages(self) -> None:
        result = alerting.check_smoke({"smokeLatest": {"ok": False, "failures": 4, "warnings": 0, "timestamp": alerting.iso(NOW)}}, NOW)
        self.assertEqual([("smoke-failed", "page")], [(i["id"], i["severity"]) for i in result])

    def test_snapshot_limit_is_24_hours(self) -> None:
        at = lambda age: {"snapshotLast": {"timestamp": alerting.iso(NOW - age), "size": 1}}
        self.assertEqual([], alerting.check_snapshot(at(24 * HOUR), NOW))
        self.assertEqual(["snapshot-stale"], ids(alerting.check_snapshot(at(24 * HOUR + 1), NOW)))

    def test_snapshot_accepts_epoch_and_iso_timestamps(self) -> None:
        self.assertEqual([], alerting.check_snapshot({"snapshotLast": {"timestamp": NOW - 5}}, NOW))
        self.assertEqual([], alerting.check_snapshot({"snapshotLast": {"timestamp": alerting.iso(NOW - 5)}}, NOW))

    def test_db_backup_limit_is_26_hours_and_failed_runs_are_left_to_failed_unit(self) -> None:
        backups = lambda age, result="success": {"dbBackups": {"kadath": {"result": result, "finishedAt": f"@{int(NOW - age)}"}}}
        self.assertEqual([], alerting.check_db_backups(backups(26 * HOUR), NOW))
        self.assertEqual(["db-backup-stale:kadath"], ids(alerting.check_db_backups(backups(26 * HOUR + 1), NOW)))
        self.assertEqual([], alerting.check_db_backups(backups(40 * HOUR, "exit-code"), NOW))

    def test_disk_thresholds(self) -> None:
        severity = lambda pct: [(i["severity"]) for i in alerting.check_disk({"diskPercent": pct}, NOW)]
        self.assertEqual([], severity(79.9))
        self.assertEqual(["warn"], severity(80))
        self.assertEqual(["warn"], severity(89.9))
        self.assertEqual(["page"], severity(90))

    def test_container_exited_limit_is_seven_days(self) -> None:
        rows = lambda age: {"exitedContainers": [{"name": "x-1", "exitedAt": NOW - age}]}
        self.assertEqual([], alerting.check_stale_containers(rows(7 * DAY), NOW))
        self.assertEqual(["container-exited:x-1"], ids(alerting.check_stale_containers(rows(7 * DAY + 1), NOW)))

    def test_deploy_behind_needs_more_than_24_hours(self) -> None:
        behind = lambda age, count=2: {"deployBehind": {"count": count, "oldestCommitAt": NOW - age}}
        self.assertEqual([], alerting.check_deploy_behind(behind(24 * HOUR), NOW))
        self.assertEqual(["deploy-behind"], ids(alerting.check_deploy_behind(behind(24 * HOUR + 1), NOW)))
        self.assertEqual([], alerting.check_deploy_behind(behind(99 * HOUR, count=0), NOW))

    def test_tailscale_key_expiry_window_is_14_days(self) -> None:
        state = lambda left, backend="Running": {"tailscale": {"backendState": backend, "keyExpiry": alerting.iso(NOW + left)}}
        self.assertEqual([], alerting.check_tailscale(state(14 * DAY + 1), NOW))
        self.assertEqual([("tailscale-key-expiry", "warn")], [(i["id"], i["severity"]) for i in alerting.check_tailscale(state(14 * DAY), NOW)])
        self.assertEqual("page", alerting.check_tailscale(state(-1), NOW)[0]["severity"])
        self.assertEqual(["tailscale-backend"], ids(alerting.check_tailscale(state(90 * DAY, "NeedsLogin"), NOW)))

    def test_certificate_window_is_14_days(self) -> None:
        certs = lambda left: {"certs": [{"name": "host.crt", "notAfter": NOW + left}]}
        self.assertEqual([], alerting.check_certs(certs(14 * DAY + 1), NOW))
        self.assertEqual(["cert-expiry:host.crt"], ids(alerting.check_certs(certs(14 * DAY), NOW)))

    def test_egress_and_m1_drift(self) -> None:
        self.assertEqual(["egress-drift:kadath"], ids(alerting.check_egress_drift({"egressDrift": {"kadath": True, "nodens": False}}, NOW)))
        self.assertEqual(["m1-drift"], ids(alerting.check_m1_drift({"m1Drift": {"state": "drift", "counts": {"add": 1}}}, NOW)))
        self.assertEqual([], alerting.check_m1_drift({"m1Drift": {"state": "clean"}}, NOW))
        self.assertIsNone(alerting.check_m1_drift({"m1Drift": {"state": "unavailable"}}, NOW))

    def test_failed_units_page(self) -> None:
        self.assertEqual([("unit-failed:argus-smoke.service", "page")], [(i["id"], i["severity"]) for i in alerting.check_failed_units({"failedUnits": ["argus-smoke.service"]}, NOW)])


class HealthTest(unittest.TestCase):
    def failures(self, *rounds):
        counts: dict = {}
        for probes in rounds:
            counts = alerting.next_health_failures(counts, probes)
        return counts

    def inputs(self, probes, counts, severity=None):
        return {"probes": probes, "healthFailures": counts, "healthSeverity": severity or {}}

    def test_two_consecutive_failures_open_and_one_success_resets(self) -> None:
        down, up = {"a": {"ok": False, "detail": "status 503"}}, {"a": {"ok": True, "detail": "ok"}}
        self.assertEqual([], alerting.check_health(self.inputs(down, self.failures(down)), NOW))
        two = self.failures(down, down)
        self.assertEqual(["health:a"], ids(alerting.check_health(self.inputs(down, two), NOW)))
        self.assertEqual({}, self.failures(down, down, up))

    def test_managed_pages_and_sandbox_warns(self) -> None:
        probes = {"managed": {"ok": False, "detail": "x"}, "sandbox": {"ok": False, "detail": "x"}}
        result = alerting.check_health(self.inputs(probes, {"managed": 2, "sandbox": 2}, {"managed": "page", "sandbox": "warn"}), NOW)
        self.assertEqual({"health:managed": "page", "health:sandbox": "warn"}, {i["id"]: i["severity"] for i in result})

    def test_unknown_probes_keep_counts(self) -> None:
        self.assertEqual({"a": 1}, alerting.next_health_failures({"a": 1}, None))


class HealthFixtureServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = 200 if self.path == "/ok" else 503
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"secret-body-token=abcdefabcdefabcdefabcdefabcdefabcdefabcdef")

    def log_message(self, *args) -> None:
        return


class ProbeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HealthFixtureServer)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def test_probe_against_local_http_server(self) -> None:
        good = alert_script.probe_health(f"http://127.0.0.1:{self.port}/ok", 200, 2)
        bad = alert_script.probe_health(f"http://127.0.0.1:{self.port}/down", 200, 2)
        self.assertTrue(good["ok"])
        self.assertEqual({"ok": False, "detail": "status 503, expected 200"}, bad)
        self.assertNotIn("secret", json.dumps(bad))

    def test_probe_refused_connection_names_only_the_class(self) -> None:
        free = http.server.ThreadingHTTPServer(("127.0.0.1", 0), HealthFixtureServer)
        port = free.server_address[1]
        free.server_close()
        result = alert_script.probe_health(f"http://127.0.0.1:{port}/", 200, 1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["detail"].startswith("request failed: "))

    def test_typed_workloads_are_active_classified_and_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "config" / "argus").mkdir(parents=True)
            health = lambda url: {"enabled": bool(url), "url": url, "expectedStatus": 200, "timeoutSeconds": 3}
            workloads = [
                {"id": "managed", "lifecycle": "active", "health": health("http://x/")},
                {"id": "sandbox", "lifecycle": "active", "health": health("http://y/")},
                {"id": "legacy", "lifecycle": "active", "health": health("http://z/")},
                {"id": "off", "lifecycle": "active", "health": health("")},
                {"id": "gone", "lifecycle": "retired", "health": health("http://g/")},
            ]
            (repo / "config" / "workloads.json").write_text(json.dumps({"workloads": workloads}))
            classified = {"managed": {"trustDomain": "personal-managed"}, "sandbox": {"trustDomain": "personal-sandbox"}, "off": {"trustDomain": "personal-sandbox"}, "gone": {"trustDomain": "personal-sandbox"}}
            (repo / "config" / "argus" / "workload-classification.json").write_text(json.dumps({"workloads": classified}))
            rows = alert_script.typed_workloads(repo)
        self.assertEqual({"managed": "page", "sandbox": "warn"}, {row["id"]: row["severity"] for row in rows})


class CollectorShapeTest(unittest.TestCase):
    def test_failed_units_parse_with_and_without_bullet(self) -> None:
        listing = "● argus-smoke.service loaded failed failed Argus scheduled smoke test\nargus-metrics.service loaded failed failed Argus metrics\n"
        self.assertEqual(["argus-smoke.service", "argus-metrics.service"], alert_script.failed_units(lambda argv: Completed(listing)))
        self.assertEqual([], alert_script.failed_units(lambda argv: Completed("")))
        self.assertIsNone(alert_script.failed_units(lambda argv: None))

    def test_db_backups_parse_systemctl_show_unix_timestamp(self) -> None:
        shown = "Result=success\nInactiveEnterTimestamp=@1794278248\n"
        result = alert_script.db_backups(lambda argv: Completed(shown), ["kadath"])
        self.assertEqual({"kadath": {"result": "success", "finishedAt": "@1794278248"}}, result)
        self.assertIsNone(alert_script.db_backups(lambda argv: Completed("", 1), ["kadath"]))

    def test_deploy_behind_against_a_real_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git = lambda *args, env=None: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env={**os.environ, **(env or {})}).stdout.strip()
            git("init", "-q", "-b", "main")
            git("config", "user.email", "t@example.invalid")
            git("config", "user.name", "t")
            git("commit", "-q", "--allow-empty", "-m", "base", env={"GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z"})
            base = git("rev-parse", "HEAD")
            git("commit", "-q", "--allow-empty", "-m", "ahead", env={"GIT_COMMITTER_DATE": "2026-01-02T00:00:00Z", "GIT_AUTHOR_DATE": "2026-01-02T00:00:00Z"})
            git("update-ref", "refs/remotes/origin/main", "HEAD")
            git("reset", "-q", "--hard", base)
            result = alert_script.deploy_behind(alert_script.run_command, repo)
            self.assertEqual(1, result["count"])
            self.assertEqual(1767312000, int(result["oldestCommitAt"]))
            self.assertEqual(["deploy-behind"], ids(alerting.check_deploy_behind({"deployBehind": result}, NOW)))
            git("update-ref", "refs/remotes/origin/main", base)
            self.assertEqual(0, alert_script.deploy_behind(alert_script.run_command, repo)["count"])

    def test_deploy_behind_unknown_without_origin_ref(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "-C", directory, "init", "-q"], check=True)
            self.assertIsNone(alert_script.deploy_behind(alert_script.run_command, Path(directory)))

    def test_exited_containers_only_counts_unmigrated_registered_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "config").mkdir()
            workloads = [
                {"id": "app", "lifecycle": "active", "runtime": {"composeProject": "app"}, "migration": {"status": "not-started"}},
                {"id": "moved", "lifecycle": "active", "runtime": {"composeProject": "moved"}, "migration": {"status": "migrated"}},
            ]
            (repo / "config" / "workloads.json").write_text(json.dumps({"workloads": workloads}))

            def run(argv):
                if argv[:2] == ["docker", "ps"]:
                    return Completed("aaa\nbbb\nccc\n")
                return Completed("/app-web-1|app|2026-08-04T10:00:00.123456789Z\n/moved-web-1|moved|2026-08-04T10:00:00Z\n/other-1|other|2026-08-04T10:00:00Z\n")

            rows = alert_script.exited_containers(run, repo)
        self.assertEqual(["app-web-1"], [row["name"] for row in rows])
        self.assertIsNotNone(rows[0]["exitedAt"])
        self.assertIsNone(alert_script.exited_containers(lambda argv: Completed("", 1), repo))

    def test_egress_drift_reads_the_last_json_line_of_the_unit_journal(self) -> None:
        journal = 'noise\n{"egressPolicyDrift": false, "reconciled": true}\nAug 1 host unit[1]: {"egressPolicyDrift": true}\n'
        self.assertEqual({"kadath": True}, alert_script.egress_drift(lambda argv: Completed(journal), ["kadath"]))
        self.assertIsNone(alert_script.egress_drift(lambda argv: Completed("", 1), ["kadath"]))

    def test_tailscale_state(self) -> None:
        payload = json.dumps({"BackendState": "Running", "Self": {"KeyExpiry": "2026-12-05T17:08:20Z"}})
        self.assertEqual({"backendState": "Running", "keyExpiry": "2026-12-05T17:08:20Z"}, alert_script.tailscale_state(lambda argv: Completed(payload)))
        self.assertIsNone(alert_script.tailscale_state(lambda argv: Completed("not json")))


class EngineTest(unittest.TestCase):
    def evaluate(self, inputs, previous, now):
        return alerting.evaluate(inputs, previous, now)

    def test_open_dedupe_resolve_with_edge_events(self) -> None:
        failing = {"failedUnits": ["argus-x.service"]}
        state, events = self.evaluate(failing, {}, NOW)
        self.assertEqual(["opened"], [e["event"] for e in events])
        alert = state["alerts"][0]
        self.assertEqual({"id", "severity", "since", "detail", "lastSeen", "acked"}, set(alert))
        self.assertEqual(alerting.iso(NOW), alert["since"])
        self.assertFalse(alert["acked"])

        again, events = self.evaluate(failing, state, NOW + 120)
        self.assertEqual([], events)
        self.assertEqual(alert["since"], again["alerts"][0]["since"])
        self.assertEqual(alerting.iso(NOW + 120), again["alerts"][0]["lastSeen"])
        self.assertEqual(1, len(again["alerts"]))

        resolved, events = self.evaluate({"failedUnits": []}, again, NOW + 240)
        self.assertEqual([], resolved["alerts"])
        self.assertEqual(["resolved"], [e["event"] for e in events])
        self.assertEqual("argus-x.service".join(["unit-failed:", ""]), events[0]["alert"]["id"])

    def test_severity_change_is_a_changed_event_not_a_new_alert(self) -> None:
        state, _ = self.evaluate({"diskPercent": 85}, {}, NOW)
        state, events = self.evaluate({"diskPercent": 95}, state, NOW + 60)
        self.assertEqual(["changed"], [e["event"] for e in events])
        self.assertEqual("page", state["alerts"][0]["severity"])
        self.assertEqual(alerting.iso(NOW), state["alerts"][0]["since"])

    def test_ack_survives_while_the_alert_stays_open(self) -> None:
        state, _ = self.evaluate({"diskPercent": 85}, {}, NOW)
        acked = {**state, "alerts": [{**state["alerts"][0], "acked": True}]}
        state, _ = self.evaluate({"diskPercent": 86}, acked, NOW + 60)
        self.assertTrue(state["alerts"][0]["acked"])

    def test_unknown_input_neither_opens_nor_resolves(self) -> None:
        state, _ = self.evaluate({"failedUnits": ["argus-x.service"], "diskPercent": 95}, {}, NOW)
        state, events = self.evaluate({"failedUnits": None, "diskPercent": 10}, state, NOW + 60)
        self.assertEqual(["unit-failed:argus-x.service"], ids(state["alerts"]))
        self.assertEqual(["resolved"], [e["event"] for e in events])  # only the disk alert, whose input is known

    def test_all_inputs_missing_is_quiet(self) -> None:
        state, events = self.evaluate({}, {}, NOW)
        self.assertEqual(([], []), (state["alerts"], events))
        self.assertEqual({"open": 0, "page": 0, "warn": 0}, state["summary"])

    def test_stale_smoke_opens_then_resolves_after_fresh_run(self) -> None:
        stale = {"smokeLatest": {"ok": True, "timestamp": alerting.iso(NOW - 30 * HOUR)}}
        state, _ = self.evaluate(stale, {}, NOW)
        self.assertEqual(["smoke-stale"], ids(state["alerts"]))
        fresh = {"smokeLatest": {"ok": True, "timestamp": alerting.iso(NOW)}}
        state, events = self.evaluate(fresh, state, NOW + 60)
        self.assertEqual(([], ["resolved"]), (state["alerts"], [e["event"] for e in events]))

    def test_details_never_carry_secrets(self) -> None:
        dirty = (
            "token=abc123 Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCDEF "
            "AGE-SECRET-KEY-1QQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQ password: hunter2 " + "x" * 400
        )
        cleaned = alerting.scrub(dirty)
        for leaked in ("abc123", "hunter2", "AGE-SECRET-KEY", "abcdefghijklmnopqrstuvwxyz0123456789"):
            self.assertNotIn(leaked, cleaned)
        self.assertLessEqual(len(cleaned), alerting.DETAIL_LIMIT)
        probes = {"a": {"ok": False, "detail": dirty}}
        found = alerting.check_health({"probes": probes, "healthFailures": {"a": 3}}, NOW)
        self.assertNotIn("hunter2", json.dumps(found))


class MainTest(unittest.TestCase):
    def test_main_writes_state_and_audits_open_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"ARGUS_ROOT": directory}):
            state_dir = Path(directory) / "runtime" / "alerts"
            inputs = [{"failedUnits": ["argus-demo.service"]}, {"failedUnits": []}]
            with mock.patch.object(alert_script, "collect_inputs", side_effect=lambda *a, **k: inputs.pop(0)), mock.patch.object(alert_script, "root", return_value=Path(directory)):
                self.assertEqual(0, alert_script.main(["--state-dir", str(state_dir)]))
                opened = json.loads((state_dir / "state.json").read_text())
                self.assertEqual(["unit-failed:argus-demo.service"], ids(opened["alerts"]))
                self.assertEqual(0, alert_script.main(["--state-dir", str(state_dir)]))
            closed = json.loads((state_dir / "state.json").read_text())
            self.assertEqual(0o644, (state_dir / "state.json").stat().st_mode & 0o777)
            audit = [json.loads(line) for line in (Path(directory) / "runtime" / "audit.log").read_text().splitlines()]
        self.assertEqual([], closed["alerts"])
        self.assertEqual(["alert.opened", "alert.resolved"], [event["action"] for event in audit])
        self.assertTrue(all(event["actor"] == "argus-alert" for event in audit))

    def test_main_tolerates_missing_files_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"ARGUS_ROOT": directory, "ARGUS_SNAPSHOT_LAST": directory + "/none.json"}):
            nothing = lambda argv: None
            with mock.patch.object(alert_script, "run_command", nothing), mock.patch.object(alert_script, "root", return_value=Path(directory)), mock.patch.object(alert_script, "m1_drift", return_value=None):
                state, _ = alerting.evaluate(alert_script.collect_inputs(Path(directory), {}, nothing), {}, NOW)
        self.assertEqual([], [a for a in state["alerts"] if a["id"] != "disk-usage"])


class ServedCertificateTest(unittest.TestCase):
    workloads = [{"url": "https://host.ts.net:8445/api/health"}, {"url": "https://host.ts.net:8445/other"}, {"url": "http://x:1/h"}]

    def test_unreachable_endpoints_are_unknown_not_clear(self) -> None:
        self.assertIsNone(alert_script.certificates(alert_script.run_command, self.workloads, lambda host, port: None))
        self.assertIsNone(alert_script.certificates(alert_script.run_command, [], lambda host, port: None))

    @unittest.skipUnless(shutil.which("openssl"), "openssl missing")
    def test_reads_not_after_from_served_pem_once_per_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key, crt = f"{directory}/k.pem", f"{directory}/c.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", crt, "-days", "3", "-subj", "/CN=t"], check=True, capture_output=True)
            pem, calls = Path(crt).read_text(), []
            rows = alert_script.certificates(alert_script.run_command, self.workloads, lambda host, port: calls.append((host, port)) or pem)
        self.assertEqual([("host.ts.net", 8445)], calls)
        self.assertEqual(["host.ts.net:8445"], [row["name"] for row in rows])
        self.assertAlmostEqual(time.time() + 3 * DAY, rows[0]["notAfter"], delta=DAY)


class PollerTest(unittest.TestCase):
    def alert(self, alert_id="unit-failed:x", severity="page", since="2026-11-10T00:00:00Z", detail="d"):
        return {"id": alert_id, "severity": severity, "since": since, "detail": detail}

    def test_new_and_changed_notify_once_and_resolved_rearms(self) -> None:
        first = self.alert()
        fresh, seen = poller.to_notify({}, [first])
        self.assertEqual([first], fresh)
        fresh, seen = poller.to_notify(seen, [first])
        self.assertEqual([], fresh)
        escalated = self.alert(severity="warn")
        self.assertEqual([escalated], poller.to_notify(seen, [escalated])[0])
        fresh, seen = poller.to_notify(seen, [])
        self.assertEqual({}, seen)
        self.assertEqual([first], poller.to_notify(seen, [first])[0])

    def test_poll_once_notifies_then_stays_quiet_and_survives_an_outage(self) -> None:
        sent = []
        ok = lambda argv: Completed(json.dumps({"alerts": [self.alert()]}))
        down = lambda argv: Completed("", 255)
        with tempfile.TemporaryDirectory() as directory:
            state, archives = Path(directory) / "seen.json", Path(directory) / "archives"
            notify = lambda message, title: sent.append((message, title))
            self.assertEqual(1, poller.poll_once(state, archives, NOW, ok, notify))
            self.assertEqual(0, poller.poll_once(state, archives, NOW + 60, ok, notify))
            self.assertEqual(0, poller.poll_once(state, archives, NOW + 120, down, notify))
            self.assertEqual(0, poller.poll_once(state, archives, NOW + 180, ok, notify))
            self.assertEqual(0o600, state.stat().st_mode & 0o777)
        self.assertEqual([("d", "Argus page: unit-failed:x")], sent)

    def test_unreachable_server_alerts_after_five_failed_polls(self) -> None:
        sent = []
        with tempfile.TemporaryDirectory() as directory:
            state, archives = Path(directory) / "seen.json", Path(directory) / "none"
            for minute in range(6):
                poller.poll_once(state, archives, NOW + 60 * minute, lambda argv: Completed("", 255), lambda m, t: sent.append(t))
        self.assertEqual(["Argus warn: poller-unreachable"], sent)

    def test_old_mac_archive_warns_and_a_missing_directory_does_not(self) -> None:
        sent = []
        ok = lambda argv: Completed(json.dumps({"alerts": []}))
        with tempfile.TemporaryDirectory() as directory:
            archives = Path(directory) / "archives"
            self.assertEqual(0, poller.poll_once(Path(directory) / "a.json", archives, NOW, ok, lambda m, t: sent.append(t)))
            archives.mkdir()
            archive = archives / "20260101T000000Z-nightly.tar.age"
            archive.write_text("x")
            os.utime(archive, (NOW - 8 * DAY, NOW - 8 * DAY))
            self.assertEqual(1, poller.poll_once(Path(directory) / "b.json", archives, NOW, ok, lambda m, t: sent.append(t)))
            os.utime(archive, (NOW - 6 * DAY, NOW - 6 * DAY))
            self.assertEqual(0, poller.poll_once(Path(directory) / "c.json", archives, NOW, ok, lambda m, t: sent.append(t)))
        self.assertEqual(["Argus warn: mac-archive-stale"], sent)

    def test_untrusted_server_text_is_scrubbed_and_passed_as_an_argument(self) -> None:
        hostile = self.alert(detail='x" & do shell script "id" token=abc123')
        sent = []
        poller.poll_once(Path(tempfile.mkdtemp()) / "s.json", Path("/nonexistent"), NOW, lambda argv: Completed(json.dumps({"alerts": [hostile]})), lambda m, t: sent.append(m))
        self.assertNotIn("abc123", sent[0])
        with mock.patch.object(poller.subprocess, "run") as run:
            poller.osascript_notify('quote " and \\', "title")
        argv = run.call_args[0][0]
        self.assertEqual(["osascript"], argv[:1])
        self.assertEqual(['quote " and \\', "title"], argv[-2:])
        self.assertNotIn('quote "', " ".join(argv[1:-2]))

    def test_fetch_alerts_rejects_garbage(self) -> None:
        for stdout in ("", "{", '{"alerts": "x"}', '{"nope": []}'):
            self.assertIsNone(poller.fetch_alerts(lambda argv, text=stdout: Completed(text)))
        self.assertIsNone(poller.fetch_alerts(lambda argv: (_ for _ in ()).throw(OSError("no ssh"))))

    def test_ssh_transport_is_non_interactive(self) -> None:
        seen = []
        poller.fetch_alerts(lambda argv: seen.append(argv) or Completed('{"alerts": []}'))
        self.assertIn("BatchMode=yes", seen[0])
        self.assertEqual("cat", seen[0][-2])


class CliAlertsTest(unittest.TestCase):
    def invoke(self, repo: Path, argv: list[str], env: dict | None = None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}):
            code = argus_cli.run(argv, repo=repo, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_smoke_status_with_history_and_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            code, output, _ = self.invoke(repo, ["smoke", "status", "--json"])
            self.assertEqual(4, code)
            self.assertTrue(json.loads(output)["error"]["retrySafe"])
            smoke = repo / "runtime" / "smoke"
            smoke.mkdir(parents=True)
            (smoke / "latest.json").write_text(json.dumps({"ok": True, "timestamp": alerting.iso(time_now() - 2 * HOUR), "failures": 0, "warnings": 0, "exitCode": 0}))
            rows = [{"timestamp": alerting.iso(time_now() - 3 * HOUR), "ok": True, "failedChecks": []}, {"timestamp": alerting.iso(time_now() - 2 * HOUR), "ok": False, "failedChecks": ["FAIL tracked secrets check ran"]}]
            (smoke / "smoke-history.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
            code, output, _ = self.invoke(repo, ["smoke", "status", "--last", "1", "--json"])
            data = json.loads(output)["data"]
            self.assertEqual(0, code)
            self.assertFalse(data["stale"])
            self.assertEqual(1, data["historyShown"])
            self.assertEqual(["FAIL tracked secrets check ran"], data["history"][0]["failedChecks"])
            code, output, _ = self.invoke(repo, ["smoke", "status", "--last", "0", "--json"])
            self.assertEqual(2, code)
            self.assertIn("between 1 and", json.loads(output)["error"]["nextAction"])

            (smoke / "latest.json").write_text(json.dumps({"ok": False, "timestamp": alerting.iso(time_now() - 2 * HOUR), "failures": 4, "warnings": 0, "exitCode": 1}))
            code, output, _ = self.invoke(repo, ["smoke", "status", "--json"])
            failed = json.loads(output)
            self.assertEqual((3, "smoke-failed"), (code, failed["error"]["code"]))
            self.assertEqual(4, failed["data"]["latest"]["failures"])

            (smoke / "latest.json").write_text(json.dumps({"ok": True, "timestamp": alerting.iso(time_now() - 30 * HOUR)}))
            code, output, _ = self.invoke(repo, ["smoke", "status", "--json"])
            stale = json.loads(output)
            self.assertEqual((3, "smoke-stale"), (code, stale["error"]["code"]))
            self.assertTrue(stale["data"]["stale"])

    def test_backup_list_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pull = Path(directory) / "pull"
            pull.mkdir()
            for name, age in (("20261109T020000Z-nightly.tar.age", 30 * HOUR), ("20261110T020000Z-nightly.tar.age", HOUR)):
                (pull / name).write_text("x")
                os.utime(pull / name, (time_now() - age, time_now() - age))
            last = Path(directory) / "snapshot-last.json"
            last.write_text(json.dumps({"timestamp": alerting.iso(time_now() - HOUR), "size": 5}))
            status = Path(directory) / "backup-status.json"
            status.write_text(json.dumps({"state": "ok", "nested": {"a": 1}}))
            env = {"ARGUS_SNAPSHOT_PULL_DIR": str(pull), "ARGUS_SNAPSHOT_LAST": str(last), "ARGUS_BACKUP_STATUS": str(status)}
            listing = json.loads(self.invoke(Path(directory), ["backup", "list", "--json"], env)[1])["data"]
            self.assertEqual(["20261110T020000Z-nightly.tar.age", "20261109T020000Z-nightly.tar.age"], [a["name"] for a in listing["archives"]])
            code, output, _ = self.invoke(Path(directory), ["backup", "freshness", "--json"], env)
            fresh = json.loads(output)
            self.assertEqual((0, True), (code, fresh["ok"]))
            self.assertTrue(fresh["data"]["allFresh"])
            self.assertNotIn("ok", fresh["data"])
            self.assertEqual({"state": "ok"}, fresh["data"]["backupStatus"])

            last.write_text(json.dumps({"timestamp": alerting.iso(time_now() - 30 * HOUR)}))
            code, output, _ = self.invoke(Path(directory), ["backup", "freshness", "--json"], env)
            stale = json.loads(output)
            self.assertEqual((3, "backup-stale"), (code, stale["error"]["code"]))
            self.assertFalse(stale["data"]["allFresh"])

            missing = {"ARGUS_SNAPSHOT_PULL_DIR": directory + "/no", "ARGUS_SNAPSHOT_LAST": directory + "/no.json", "ARGUS_BACKUP_STATUS": directory + "/no2.json"}
            code, output, _ = self.invoke(Path(directory), ["backup", "freshness", "--json"], missing)
            unknown = json.loads(output)
            self.assertEqual((4, "backup-evidence-unavailable"), (code, unknown["error"]["code"]))
            self.assertEqual({"unavailable"}, {row["state"] for row in unknown["data"]["sources"]})
            code, output, _ = self.invoke(Path(directory), ["backup", "list", "--json"], missing)
            self.assertEqual((4, "backup-pull-dir-unavailable"), (code, json.loads(output)["error"]["code"]))

    def test_alerts_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            code, output, _ = self.invoke(repo, ["alerts", "--json"])
            self.assertEqual((4, "alert-state-unavailable"), (code, json.loads(output)["error"]["code"]))
            state_path = repo / "runtime" / "alerts" / "state.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(json.dumps({"generatedAt": alerting.iso(time_now()), "alerts": [{"id": "x", "severity": "warn"}]}))
            code, output, _ = self.invoke(repo, ["alerts", "--json"])
            quiet = json.loads(output)["data"]
            self.assertEqual((0, 1, 0, False), (code, quiet["open"], quiet["page"], quiet["stale"]))

            state, _ = alerting.evaluate({"failedUnits": ["argus-x.service"]}, {}, time_now())
            state_path.write_text(json.dumps(state))
            code, output, _ = self.invoke(repo, ["alerts", "--json"])
            paged = json.loads(output)
            self.assertEqual((3, "alerts-page-open"), (code, paged["error"]["code"]))
            self.assertEqual((1, 1, False), (paged["data"]["open"], paged["data"]["page"], paged["data"]["stale"]))
            code, output, error = self.invoke(repo, ["alerts"])
            self.assertEqual(3, code)
            self.assertIn("unit-failed:argus-x.service", output)
            self.assertIn("ERROR alerts-page-open", error)

            state_path.write_text(json.dumps({"generatedAt": alerting.iso(time_now() - 41 * DAY), "alerts": []}))
            code, output, _ = self.invoke(repo, ["alerts", "--json"])
            old = json.loads(output)
            self.assertEqual((3, "alert-state-stale"), (code, old["error"]["code"]))
            self.assertTrue(old["data"]["stale"])

            for content in ("garbage", json.dumps({"generatedAt": alerting.iso(time_now()), "alerts": 5})):
                with self.subTest(content=content):
                    state_path.write_text(content)
                    code, output, _ = self.invoke(repo, ["alerts", "--json"])
                    unreadable = json.loads(output)["error"]
                    self.assertEqual((4, "alert-state-unreadable"), (code, unreadable["code"]))
                    self.assertNotIn("exists yet", unreadable["message"])

    def test_dashboard_state_exposes_sanitized_alerts(self) -> None:
        import argus_common

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {"ARGUS_ROOT": directory}):
            self.assertEqual({"available": False, "alerts": []}, argus_common.alert_state())
            (Path(directory) / "runtime" / "alerts").mkdir(parents=True)
            row = {"id": "x", "severity": "warn", "since": "s", "detail": "d", "lastSeen": "l", "acked": False, "internal": "drop"}
            (Path(directory) / "runtime" / "alerts" / "state.json").write_text(json.dumps({"generatedAt": "g", "alerts": [row]}))
            result = argus_common.alert_state()
        self.assertTrue(result["available"])
        self.assertNotIn("internal", result["alerts"][0])

    def test_dashboard_banner_is_next_to_exposure_alert_and_reads_alerts(self) -> None:
        html = (ROOT / "control-plane" / "dashboard" / "generate_dashboard.py").read_text()
        self.assertLess(html.index('id="exposure-alert"'), html.index('id="alert-banner"'))
        self.assertIn("state?.alerts", html)
        self.assertIn('alertBanner.dataset.state = open.length ? "open" : "clear"', html)


class UnitFilesTest(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text()

    def test_alert_units(self) -> None:
        service, timer = self.read("systemd/argus-alert.service"), self.read("systemd/argus-alert.timer")
        self.assertIn("ExecStart=/usr/bin/python3 /srv/argus/scripts/argus-alert\n", service)
        self.assertIn("User=oreo", service)
        self.assertIn("ReadWritePaths=/srv/argus/runtime", service)
        self.assertIn("OnBootSec=2min", timer)
        self.assertIn("OnUnitActiveSec=2min", timer)
        self.assertIn("argus-alert --trigger %i", self.read("systemd/argus-alert-unit@.service"))

    def test_failure_dropins_point_at_the_alert_unit(self) -> None:
        for unit in ("argus-smoke.service", "argus-metrics.service", "argus-estate-refresh.service", "argus-workload-db-backup@.service", "argus-backup-snapshot.service"):
            self.assertEqual("[Unit]\nOnFailure=argus-alert-unit@%n.service\n", self.read(f"systemd/{unit}.d/onfailure.conf"), unit)

    def test_smoke_timer_runs_every_six_hours_with_jitter_and_matches_template(self) -> None:
        timer = self.read("systemd/argus-smoke.timer")
        self.assertIn("OnCalendar=*-*-* 00/6:00:00", timer)
        self.assertIn("RandomizedDelaySec=15m", timer)
        self.assertIn("Persistent=true", timer)
        self.assertEqual(timer, self.read("templates/systemd/argus-smoke.timer"))

    def test_poller_plist(self) -> None:
        import plistlib

        plist = plistlib.loads((ROOT / "ops" / "launchd" / "dev.argus.alert-poller.plist").read_bytes())
        self.assertEqual("dev.argus.alert-poller", plist["Label"])
        self.assertEqual(60, plist["StartInterval"])
        self.assertTrue(plist["ProgramArguments"][-1].endswith("scripts/argus-alert-poller"))

    def test_sources_ignore_oversized_and_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            big, bad = Path(directory) / "big.json", Path(directory) / "bad.json"
            big.write_text('{"a": "' + "x" * (sources.MAX_JSON_BYTES + 1) + '"}')
            bad.write_text("{")
            self.assertEqual((None, None, None), (sources.read_json(big), sources.read_json(bad), sources.read_json(Path(directory) / "missing")))


def time_now() -> float:
    import time

    return time.time()


if __name__ == "__main__":
    unittest.main()
