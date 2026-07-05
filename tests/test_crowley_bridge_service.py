#!/usr/bin/env python3
"""Tests for durable ChatGPT bridge LaunchAgent service manager."""

from __future__ import annotations

import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import crowley_bridge_service as service  # noqa: E402


class CrowleyBridgeServiceTests(unittest.TestCase):
    def test_render_plist_contains_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_script = repo / "scripts" / "run_durable_bridge.sh"
            run_script.parent.mkdir(parents=True)
            run_script.write_text("#!/bin/bash\n", encoding="utf-8")
            log_file = repo / ".crowley" / "chatgpt_bridge" / "service.log"
            payload = service.render_plist(
                repo_root=repo,
                run_script=run_script,
                log_file=log_file,
            )
        self.assertEqual(payload["Label"], service.LABEL)
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])
        self.assertIn("EnvironmentVariables", payload)
        args = payload["ProgramArguments"]
        self.assertIsInstance(args, list)
        self.assertEqual(args[0], "/bin/bash")
        self.assertTrue(str(args[1]).endswith("run_durable_bridge.sh"))

    def test_preflight_requires_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with mock.patch.object(service, "ROOT", repo), mock.patch.object(
                service, "RUN_SCRIPT", repo / "scripts" / "run_durable_bridge.sh"
            ), mock.patch.object(service, "CONFIG_PATH", repo / "cloudflared" / "config.yml"), mock.patch.object(
                service, "cloudflared_binary", return_value="/usr/local/bin/cloudflared"
            ):
                service.RUN_SCRIPT.parent.mkdir(parents=True)
                service.RUN_SCRIPT.write_text("#!/bin/bash\n", encoding="utf-8")
                with self.assertRaises(FileNotFoundError):
                    service.preflight()

    def test_install_writes_plist_and_bootstraps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            repo = Path(tmp) / "repo"
            config = repo / "cloudflared" / "config.yml"
            run_script = repo / "scripts" / "run_durable_bridge.sh"
            config.parent.mkdir(parents=True)
            run_script.parent.mkdir(parents=True)
            config.write_text("tunnel: test\n", encoding="utf-8")
            run_script.write_text("#!/bin/bash\n", encoding="utf-8")

            paths = service.ServicePaths(
                repo_root=repo,
                launch_agents_dir=launch_agents,
                installed_plist=launch_agents / service.PLIST_NAME,
                domain_target="gui/501",
            )

            with mock.patch.object(service, "ROOT", repo), mock.patch.object(
                service, "RUN_SCRIPT", run_script
            ), mock.patch.object(service, "CONFIG_PATH", config), mock.patch.object(
                service, "BRIDGE_DIR", repo / ".crowley" / "chatgpt_bridge"
            ), mock.patch.object(service, "SERVICE_LOG", repo / ".crowley" / "chatgpt_bridge" / "service.log"), mock.patch.object(
                service, "cloudflared_binary", return_value="/usr/local/bin/cloudflared"
            ), mock.patch.object(service, "_service_loaded", return_value=False), mock.patch.object(
                service, "_run_launchctl", return_value=mock.Mock(returncode=0, stderr="")
            ) as launchctl_mock, mock.patch.object(service, "write_example_plist") as write_example_mock:
                service.install(paths=paths)
                write_example_mock.assert_not_called()

            self.assertTrue(paths.installed_plist.is_file())
            payload = plistlib.loads(paths.installed_plist.read_bytes())
            self.assertEqual(payload["Label"], service.LABEL)
            launchctl_mock.assert_called()

    def test_status_missing_plist_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            paths = service.ServicePaths(
                repo_root=Path(tmp) / "repo",
                launch_agents_dir=launch_agents,
                installed_plist=launch_agents / service.PLIST_NAME,
                domain_target="gui/501",
            )
            with mock.patch.object(service, "_connector_process_running", return_value=False):
                code = service.status(paths=paths)
            self.assertEqual(code, 2)

    def test_committed_example_plist_uses_placeholder_paths(self) -> None:
        example = ROOT / "launchd" / f"{service.PLIST_NAME}.example"
        self.assertTrue(example.is_file(), f"missing committed example: {example}")
        payload = plistlib.loads(example.read_bytes())
        text = example.read_text(encoding="utf-8")
        self.assertNotIn("/private/var/folders", text)
        self.assertNotIn("/tmp/", text)
        self.assertNotIn("/var/folders/", text)

        args = payload["ProgramArguments"]
        self.assertIsInstance(args, list)
        self.assertIn("/path/to/crowley", str(args[1]))
        self.assertEqual(payload["WorkingDirectory"], "/path/to/crowley")
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertIn("/path/to/crowley", str(payload[key]))

    def test_write_example_plist_uses_placeholder_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "example.plist"
            service.write_example_plist(output=output)
            payload = plistlib.loads(output.read_bytes())
            self.assertEqual(payload["WorkingDirectory"], "/path/to/crowley")

    def test_uninstall_removes_plist_not_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            launch_agents = home / "Library" / "LaunchAgents"
            launch_agents.mkdir(parents=True)
            plist = launch_agents / service.PLIST_NAME
            plist.write_text("plist", encoding="utf-8")
            creds = Path(tmp) / "repo" / ".crowley" / "cloudflared"
            creds.mkdir(parents=True)
            (creds / "tunnel.json").write_text("{}", encoding="utf-8")

            paths = service.ServicePaths(
                repo_root=Path(tmp) / "repo",
                launch_agents_dir=launch_agents,
                installed_plist=plist,
                domain_target="gui/501",
            )
            with mock.patch.object(service, "_service_loaded", return_value=False):
                service.uninstall(paths=paths)
            self.assertFalse(plist.exists())
            self.assertTrue((creds / "tunnel.json").exists())


if __name__ == "__main__":
    unittest.main()
