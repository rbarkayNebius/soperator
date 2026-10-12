import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


CHECK_RUNNER_PATH = Path(__file__).with_name("check_runner.py")


class CheckRunnerOnOkContextTest(unittest.TestCase):
    def load_runner(self, context: str, tmpdir: str):
        env = {
            "SLURMD_NODENAME": "worker-1",
            "CHECKS_OUTPUTS_BASE_DIR": tmpdir,
            "CHECKS_CONTEXT": context,
            "CHECKS_CONFIG": str(Path(tmpdir) / "checks.json"),
            "CHECKS_RUNNER_OUTPUT": "/dev/null",
        }
        patcher = mock.patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

        module_name = f"check_runner_under_test_{context}_{id(self)}"
        spec = importlib.util.spec_from_file_location(module_name, CHECK_RUNNER_PATH)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        return runner

    def test_undrain_on_ok_is_ignored_outside_hc_program(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = self.load_runner("prolog", tmpdir)
            check = runner.Check(
                name="boot_disk_full",
                command="/usr/bin/true",
                on_ok="undrain",
                reason_base="[user_problem] $name",
                log="check.out",
            )

            def get_node_info():
                raise AssertionError("prolog on_ok=undrain must not read Slurm node info")

            def undrain_node():
                raise AssertionError("prolog on_ok=undrain must not undrain Slurm nodes")

            runner.get_node_info = get_node_info
            runner.undrain_node = undrain_node

            runner.run_check(check, in_jail=True)

    def test_undrain_on_ok_still_runs_in_hc_program(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = self.load_runner("hc_program", tmpdir)
            check = runner.Check(
                name="boot_disk_full",
                command="/usr/bin/true",
                on_ok="undrain",
                reason_base="[user_problem] $name",
                log="check.out",
            )
            calls = []

            runner.get_node_info = lambda: runner.NodeInfo(
                state_flags=["DRAIN"],
                reason="[user_problem] boot_disk_full: disk ok [hc_program]",
            )
            runner.undrain_node = lambda: calls.append("undrain")

            runner.run_check(check, in_jail=True)

            self.assertEqual(["undrain"], calls)

    def test_uncomment_on_ok_is_ignored_outside_hc_program(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = self.load_runner("epilog", tmpdir)
            check = runner.Check(
                name="some_check",
                command="/usr/bin/true",
                on_ok="uncomment",
                reason_base="[node_problem] $name",
                log="check.out",
            )

            def get_node_info():
                raise AssertionError("epilog on_ok=uncomment must not read Slurm node info")

            def uncomment_node():
                raise AssertionError("epilog on_ok=uncomment must not uncomment Slurm nodes")

            runner.get_node_info = get_node_info
            runner.uncomment_node = uncomment_node

            runner.run_check(check, in_jail=True)

    def test_uncomment_on_ok_still_runs_in_hc_program(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = self.load_runner("hc_program", tmpdir)
            check = runner.Check(
                name="some_check",
                command="/usr/bin/true",
                on_ok="uncomment",
                reason_base="[node_problem] $name",
                log="check.out",
            )
            calls = []

            runner.get_node_info = lambda: runner.NodeInfo(
                comment="[node_problem] some_check: recovered [hc_program]",
            )
            runner.uncomment_node = lambda: calls.append("uncomment")

            runner.run_check(check, in_jail=True)

            self.assertEqual(["uncomment"], calls)


class LogFileSymlinkTest(unittest.TestCase):
    ATTACKER_UID = 65534

    def plant_symlink(self, target: Path, link: Path):
        link.symlink_to(target)
        if os.geteuid() == 0:
            os.lchown(link, self.ATTACKER_UID, self.ATTACKER_UID)

    def test_check_log_does_not_follow_planted_symlink(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = CheckRunnerOnOkContextTest.load_runner(self, "epilog", tmpdir)
            target = Path(tmpdir) / "victim"
            target.write_text("original\n", encoding="utf-8")
            log = Path(tmpdir) / "check.out"
            self.plant_symlink(target, log)
            check = runner.Check(name="echo", command="echo from-check", log="check.out")

            runner.run_check(check, in_jail=True)

            self.assertEqual("original\n", target.read_text(encoding="utf-8"))
            if os.geteuid() == 0:
                self.assertFalse(log.is_symlink())
                self.assertEqual("from-check\n", log.read_text(encoding="utf-8"))

    def test_open_log_file_does_not_create_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = CheckRunnerOnOkContextTest.load_runner(self, "epilog", tmpdir)
            target = Path(tmpdir) / "ld.so.preload"
            log = Path(tmpdir) / "worker-1.check_runner.epilog.out"
            self.plant_symlink(target, log)

            try:
                os.close(runner.open_log_file(str(log)))
            except PermissionError:
                pass

            self.assertFalse(target.exists())

    def test_open_log_file_refuses_symlinked_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = CheckRunnerOnOkContextTest.load_runner(self, "epilog", tmpdir)
            target_dir = Path(tmpdir) / "etc"
            target_dir.mkdir()
            self.plant_symlink(target_dir, Path(tmpdir) / "slurm_scripts")

            with self.assertRaises(OSError):
                runner.open_log_file(str(Path(tmpdir) / "slurm_scripts" / "check.out"))

            self.assertEqual([], list(target_dir.iterdir()))

    def test_open_log_file_truncates_own_regular_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = CheckRunnerOnOkContextTest.load_runner(self, "epilog", tmpdir)
            log = Path(tmpdir) / "check.out"
            log.write_text("previous run\n", encoding="utf-8")

            with os.fdopen(runner.open_log_file(str(log)), "w") as f:
                f.write("new run\n")

            self.assertEqual("new run\n", log.read_text(encoding="utf-8"))


def load_check_runner():
    required_env = {
        "SLURMD_NODENAME": "worker-1",
        "CHECKS_OUTPUTS_BASE_DIR": "/opt/soperator-outputs",
        "CHECKS_CONTEXT": "hc_program",
        "CHECKS_CONFIG": "/opt/slurm_scripts/checks.json",
    }
    with mock.patch.dict(os.environ, required_env):
        spec = importlib.util.spec_from_file_location(
            "check_runner_under_test", CHECK_RUNNER_PATH
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


check_runner = load_check_runner()


class NodeRealMemoryMetadataTest(unittest.TestCase):
    def setUp(self):
        check_runner.get_node_real_memory_bytes.cache_clear()

    def test_reads_real_memory_from_local_metadata_without_node_rpc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_file = Path(tmpdir) / "node_metadata.env"
            metadata_file.write_text(
                "IGNORED=value\n"
                "SOPERATOR_NODE_REAL_MEMORY_BYTES=999292928\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    check_runner, "SOPERATOR_NODE_METADATA_FILE", str(metadata_file)
                ),
                mock.patch.object(check_runner, "get_node_info") as get_node_info,
            ):
                result = check_runner.get_node_real_memory_bytes()

            self.assertEqual(999292928, result)
            get_node_info.assert_not_called()

    def test_exports_local_real_memory_for_checks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_file = Path(tmpdir) / "node_metadata.env"
            metadata_file.write_text(
                "SOPERATOR_NODE_REAL_MEMORY_BYTES=999292928\n",
                encoding="utf-8",
            )
            check = check_runner.Check(need_env=["CHECKS_NODE_REAL_MEM_BYTES"])

            with (
                mock.patch.object(
                    check_runner, "SOPERATOR_NODE_METADATA_FILE", str(metadata_file)
                ),
                mock.patch.object(check_runner, "get_node_info") as get_node_info,
                mock.patch.dict(os.environ, {}, clear=False),
            ):
                check_runner.export_needed_env(check)
                exported_value = os.environ["CHECKS_NODE_REAL_MEM_BYTES"]

            self.assertEqual("999292928", exported_value)
            get_node_info.assert_not_called()

    def test_falls_back_to_slurm_when_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_file = Path(tmpdir) / "missing.env"
            node_info = check_runner.NodeInfo(real_memory_bytes=2147483648)

            with (
                mock.patch.object(
                    check_runner, "SOPERATOR_NODE_METADATA_FILE", str(missing_file)
                ),
                mock.patch.object(
                    check_runner, "get_node_info", return_value=node_info
                ) as get_node_info,
            ):
                result = check_runner.get_node_real_memory_bytes()

            self.assertEqual(2147483648, result)
            get_node_info.assert_called_once_with()

    def test_falls_back_to_slurm_when_metadata_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata_file = Path(tmpdir) / "node_metadata.env"
            metadata_file.write_text(
                "SOPERATOR_NODE_REAL_MEMORY_BYTES=invalid\n", encoding="utf-8"
            )
            node_info = check_runner.NodeInfo(real_memory_bytes=1073741824)

            with (
                mock.patch.object(
                    check_runner, "SOPERATOR_NODE_METADATA_FILE", str(metadata_file)
                ),
                mock.patch.object(
                    check_runner, "get_node_info", return_value=node_info
                ) as get_node_info,
            ):
                result = check_runner.get_node_real_memory_bytes()

            self.assertEqual(1073741824, result)
            get_node_info.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
