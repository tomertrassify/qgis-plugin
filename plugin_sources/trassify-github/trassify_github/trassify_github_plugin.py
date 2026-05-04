from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QProcess, QProcessEnvironment, QSettings
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QToolBar,
)
from qgis.core import Qgis, QgsProject


class TrassifyGithubPlugin:
    TOOLBAR_NAME = "Trassify Github"
    TOOLBAR_OBJECT_NAME = "TrassifyGithubToolbar"
    SETTINGS_KEY = "trassify_github/repo_root"
    LOG_TAG = "Trassify Github"

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.pull_action = None
        self.push_action = None
        self.toolbar = None
        self._plugin_menu = f"&{self.TOOLBAR_NAME}"
        self._plugin_dir = Path(__file__).resolve().parent
        self._saved_repo_root = ""
        self._process = None
        self._process_output = []
        self._sequence_output = []
        self._pending_commands = []
        self._final_success_message = ""
        self._current_command = ""
        self._current_command_repo = ""
        self._git_executable = ""

    def initGui(self):
        self._create_actions()

        self.toolbar = self._find_toolbar()
        if self._is_qt_object_alive(self.toolbar):
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, self.toolbar)
            self._safe_qt_call(self.toolbar.deleteLater)

        self.toolbar = self.iface.addToolBar(self.TOOLBAR_NAME)
        self.toolbar.setObjectName(self.TOOLBAR_OBJECT_NAME)
        self.toolbar.setToolTip(
            "Trassify Github: Repository verbinden, pull ausfuehren, push ausfuehren."
        )
        self.toolbar.setWindowIcon(self._icon("SimpleIconsGithub.svg"))
        self.toolbar.addAction(self.action)
        self.toolbar.addAction(self.pull_action)
        self.toolbar.addAction(self.push_action)

        self.iface.addPluginToMenu(self._plugin_menu, self.action)
        self.iface.addPluginToMenu(self._plugin_menu, self.pull_action)
        self.iface.addPluginToMenu(self._plugin_menu, self.push_action)

        self._load_saved_repo()
        self._update_action_state()

    def unload(self):
        if self._command_running():
            self._process.kill()
            self._process.waitForFinished(2000)
            self._cleanup_process()

        toolbar = self._find_toolbar()
        actions = [self.action, self.pull_action, self.push_action]

        self.action = None
        self.pull_action = None
        self.push_action = None
        self.toolbar = None

        for action in actions:
            if not self._is_qt_object_alive(action):
                continue
            self._safe_qt_call(self.iface.removePluginMenu, self._plugin_menu, action)
            self._safe_qt_call(action.deleteLater)

        if self._is_qt_object_alive(toolbar):
            self._safe_qt_call(self.iface.mainWindow().removeToolBar, toolbar)
            self._safe_qt_call(toolbar.deleteLater)

    def run(self):
        self._select_and_save_repo()

    def _create_actions(self):
        self.action = QAction(
            self._icon("SimpleIconsGithub.svg"),
            "GitHub-Ordner verbinden",
            self.iface.mainWindow(),
        )
        self.action.setObjectName("trassifyGithubConnectAction")
        self.action.setStatusTip("Trassify Github: Git-Repository verbinden und speichern")
        self.action.triggered.connect(self.run)

        self.pull_action = QAction(
            self._icon("IcBaselineGetApp.svg"),
            "Git Pull",
            self.iface.mainWindow(),
        )
        self.pull_action.setObjectName("trassifyGithubPullAction")
        self.pull_action.setStatusTip("Trassify Github: git pull fuer das gespeicherte Repository")
        self.pull_action.triggered.connect(lambda: self._run_git_command("pull"))

        self.push_action = QAction(
            self._icon("BxPaperPlane.svg"),
            "Git Commit + Push",
            self.iface.mainWindow(),
        )
        self.push_action.setObjectName("trassifyGithubPushAction")
        self.push_action.setStatusTip(
            "Trassify Github: git add, git commit und git push fuer das gespeicherte Repository"
        )
        self.push_action.triggered.connect(lambda: self._run_git_command("push"))

    def _select_and_save_repo(self):
        if self._command_running():
            return

        start_dir = self._saved_repo_root or self._default_start_directory()
        selected_dir = QFileDialog.getExistingDirectory(
            self.iface.mainWindow(),
            "Git-Ordner waehlen",
            start_dir,
            QFileDialog.ShowDirsOnly,
        )
        if not selected_dir:
            return

        repo_probe = self._probe_repo_root(selected_dir)
        if repo_probe["error"]:
            self._show_git_missing_error()
            return

        repo_root = repo_probe["repo_root"]
        if not repo_root:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.TOOLBAR_NAME,
                "Im gewaehlten Ordner wurde kein Git-Repository gefunden.",
            )
            return

        self._save_repo_root(repo_root)
        self._update_action_state()

        repo_kind = "Git-Repository"
        origin_url = self._read_git_output(
            ["git", "-C", repo_root, "remote", "get-url", "origin"]
        )
        if origin_url and "github.com" in origin_url.lower():
            repo_kind = "GitHub-Repository"

        self.iface.messageBar().pushMessage(
            self.LOG_TAG,
            f"{repo_kind} gespeichert: {repo_root}",
            level=Qgis.Success,
            duration=4,
        )

    def _run_git_command(self, subcommand):
        if not self._ensure_git_available():
            self._update_action_state()
            return

        repo_root = self._resolve_saved_repo_root()
        if not repo_root:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.TOOLBAR_NAME,
                "Bitte zuerst ueber das GitHub-Symbol einen Repository-Ordner verbinden.",
            )
            return

        if self._command_running():
            return

        self._current_command_repo = repo_root
        command_specs = self._build_command_sequence(subcommand, repo_root)
        if not command_specs:
            return

        self._pending_commands = list(command_specs)
        self._sequence_output = []
        self._update_action_state()
        self._start_next_command()

    def _read_stdout(self):
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if text:
            self._process_output.append(text)
            self._sequence_output.append(text)

    def _read_stderr(self):
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
        if text:
            self._process_output.append(text)
            self._sequence_output.append(text)

    def _command_error(self, error):
        if error != QProcess.FailedToStart:
            return

        self._show_command_failure(
            self._current_command or "git",
            self._current_command_repo,
            "Git konnte nicht gestartet werden. Ist Git im Systempfad verfuegbar?",
        )
        self._cleanup_process()
        self._update_action_state()

    def _command_finished(self, exit_code, exit_status):
        self._read_stdout()
        self._read_stderr()

        command_text = self._current_command or "git"
        repo_root = self._current_command_repo
        details = self._combined_process_output()

        if exit_status == QProcess.NormalExit and exit_code == 0:
            self._cleanup_process()
            if self._pending_commands:
                self._start_next_command()
                return

            summary = self._final_success_message or self._summarize_sequence_output()
            if not summary:
                summary = f"{command_text} erfolgreich."
            self.iface.messageBar().pushMessage(
                self.LOG_TAG,
                summary,
                level=Qgis.Success,
                duration=5,
            )
        else:
            detail_text = details or f"{command_text} wurde mit Exit-Code {exit_code} beendet."
            self._show_command_failure(command_text, repo_root, detail_text)
            self._pending_commands = []

        self._cleanup_process()
        self._update_action_state()

    def _load_saved_repo(self):
        settings = QSettings()
        stored_value = settings.value(self.SETTINGS_KEY, "", type=str)
        self._saved_repo_root = str(stored_value or "").strip()
        self._resolve_saved_repo_root()

    def _resolve_saved_repo_root(self):
        repo_root = str(self._saved_repo_root or "").strip()
        if not repo_root:
            self._saved_repo_root = ""
            return ""

        repo_probe = self._probe_repo_root(repo_root)
        if repo_probe["error"]:
            return self._saved_repo_root

        resolved_root = repo_probe["repo_root"]
        if not resolved_root:
            self._clear_saved_repo_root()
            return ""

        if resolved_root != repo_root:
            self._save_repo_root(resolved_root)

        return self._saved_repo_root

    def _save_repo_root(self, repo_root):
        normalized_root = str(repo_root or "").strip()
        self._saved_repo_root = normalized_root
        QSettings().setValue(self.SETTINGS_KEY, normalized_root)

    def _clear_saved_repo_root(self):
        self._saved_repo_root = ""
        QSettings().remove(self.SETTINGS_KEY)

    def _update_action_state(self):
        repo_root = self._resolve_saved_repo_root()
        is_running = self._command_running()
        git_available = bool(self._resolve_git_executable())

        connect_tooltip = "Trassify Github: Repository-Ordner auswaehlen und speichern."
        if repo_root:
            connect_tooltip += f"\nVerbunden: {repo_root}"

        pull_tooltip = "Trassify Github: git pull fuer das verbundene Repository."
        push_tooltip = (
            "Trassify Github: git add -A, git commit und git push fuer das verbundene Repository."
        )
        if repo_root:
            detail_lines = [f"Repo: {repo_root}"]
            if git_available:
                branch_name = self._read_git_output(
                    ["git", "-C", repo_root, "branch", "--show-current"]
                )
                origin_url = self._read_git_output(
                    ["git", "-C", repo_root, "remote", "get-url", "origin"]
                )
                if branch_name:
                    detail_lines.append(f"Branch: {branch_name}")
                if origin_url:
                    detail_lines.append(f"Origin: {origin_url}")
            repo_details = "\n".join(detail_lines)
            connect_tooltip = f"{connect_tooltip}\n{repo_details}"
            pull_tooltip = f"{pull_tooltip}\n{repo_details}"
            push_tooltip = f"{push_tooltip}\n{repo_details}"
            self.action.setText("GitHub-Ordner wechseln")
        else:
            pull_tooltip += "\nNoch kein Repository verbunden."
            push_tooltip += "\nNoch kein Repository verbunden."
            self.action.setText("GitHub-Ordner verbinden")

        if not git_available:
            missing_git_hint = "\nGit wurde in QGIS nicht gefunden."
            connect_tooltip = f"{connect_tooltip}{missing_git_hint}"
            pull_tooltip = f"{pull_tooltip}{missing_git_hint}"
            push_tooltip = f"{push_tooltip}{missing_git_hint}"

        self.action.setToolTip(connect_tooltip)
        self.pull_action.setToolTip(pull_tooltip)
        self.push_action.setToolTip(push_tooltip)

        self.action.setEnabled(not is_running)
        self.pull_action.setEnabled(bool(repo_root) and bool(git_available) and not is_running)
        self.push_action.setEnabled(bool(repo_root) and bool(git_available) and not is_running)

    def _show_command_failure(self, command_text, repo_root, detail_text):
        self.iface.messageBar().pushMessage(
            self.LOG_TAG,
            f"{command_text} fehlgeschlagen.",
            level=Qgis.Warning,
            duration=6,
        )

        dialog = QMessageBox(self.iface.mainWindow())
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle(self.TOOLBAR_NAME)
        dialog.setText(f"{command_text} ist fehlgeschlagen.")
        if repo_root:
            dialog.setInformativeText(f"Repository: {repo_root}")
        if detail_text:
            dialog.setDetailedText(detail_text)
        dialog.exec_()

    def _summarize_process_output(self):
        for chunk in reversed(self._process_output):
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            if not lines:
                continue
            return f"{self._current_command}: {lines[-1]}"
        return ""

    def _summarize_sequence_output(self):
        for chunk in reversed(self._sequence_output):
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            if not lines:
                continue
            return lines[-1]
        return ""

    def _combined_process_output(self):
        parts = self._sequence_output or self._process_output
        return "".join(parts).strip()

    def _command_running(self):
        return self._process is not None and self._process.state() != QProcess.NotRunning

    def _cleanup_process(self):
        if self._process is not None:
            self._process.deleteLater()
        self._process = None
        self._process_output = []
        self._current_command = ""
        if not self._pending_commands:
            self._current_command_repo = ""
            self._sequence_output = []
            self._final_success_message = ""

    def _find_toolbar(self):
        try:
            return self.iface.mainWindow().findChild(QToolBar, self.TOOLBAR_OBJECT_NAME)
        except Exception:
            return self.toolbar

    def _build_command_sequence(self, subcommand, repo_root):
        if subcommand == "pull":
            self._final_success_message = "git pull erfolgreich."
            return [self._command_spec("git pull", ["pull"])]

        if subcommand != "push":
            self._final_success_message = ""
            return [self._command_spec(f"git {subcommand}", [subcommand])]

        command_specs = []
        has_local_changes = self._has_local_changes(repo_root)
        if has_local_changes:
            commit_message = self._prompt_commit_message(repo_root)
            if commit_message is None:
                return []
            command_specs.append(self._command_spec("git add -A", ["add", "-A"]))
            command_specs.append(
                self._command_spec(
                    f"git commit -m {commit_message}",
                    ["commit", "-m", commit_message],
                )
            )
            self._final_success_message = "Commit erstellt und Push erfolgreich."
        else:
            self._final_success_message = "git push erfolgreich."

        command_specs.append(self._command_spec("git push", ["push"]))
        return command_specs

    def _command_spec(self, display_text, arguments):
        return {
            "display_text": display_text,
            "arguments": list(arguments),
        }

    def _start_next_command(self):
        if not self._pending_commands:
            self._update_action_state()
            return

        git_program = self._resolve_git_executable()
        if not git_program:
            self._pending_commands = []
            self._show_git_missing_error()
            self._cleanup_process()
            self._update_action_state()
            return

        command_spec = self._pending_commands.pop(0)
        self._current_command = command_spec["display_text"]
        self._process_output = []

        self._process = QProcess(self.iface.mainWindow())
        self._process.setWorkingDirectory(self._current_command_repo)
        self._process.setProgram(git_program)
        self._process.setArguments(command_spec["arguments"])

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("GIT_TERMINAL_PROMPT", "0")
        self._process.setProcessEnvironment(environment)

        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.errorOccurred.connect(self._command_error)
        self._process.finished.connect(self._command_finished)

        self.iface.messageBar().pushMessage(
            self.LOG_TAG,
            f"{self._current_command} startet fuer {self._current_command_repo}",
            level=Qgis.Info,
            duration=3,
        )
        self._process.start()

    def _has_local_changes(self, repo_root):
        status_output = self._read_git_output(
            ["git", "-C", repo_root, "status", "--porcelain"]
        )
        return bool(status_output.strip())

    def _prompt_commit_message(self, repo_root):
        default_message = (
            f"Update via Trassify Github {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        repo_name = Path(repo_root).name
        commit_message, accepted = QInputDialog.getText(
            self.iface.mainWindow(),
            self.TOOLBAR_NAME,
            f"Commit-Nachricht fuer {repo_name}:",
            QLineEdit.Normal,
            default_message,
        )
        if not accepted:
            return None

        commit_message = str(commit_message or "").strip()
        return commit_message or default_message

    def _is_qt_object_alive(self, obj):
        if obj is None:
            return False
        try:
            return not sip.isdeleted(obj)
        except Exception:
            return False

    def _safe_qt_call(self, func, *args):
        try:
            return func(*args)
        except Exception:
            return None

    def _default_start_directory(self):
        project_home = str(QgsProject.instance().homePath() or "").strip()
        if project_home:
            return project_home
        return str(Path.home())

    def _icon(self, filename):
        return QIcon(str(self._plugin_dir / filename))

    def _detect_repo_root(self, selected_dir):
        return self._probe_repo_root(selected_dir)["repo_root"]

    def _read_git_output(self, command):
        arguments = list(command)
        if arguments and Path(arguments[0]).name.lower().startswith("git"):
            arguments = arguments[1:]

        result = self._run_git(arguments)
        if not result["ok"]:
            return ""

        return result["stdout"]

    def _git_env(self):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def _ensure_git_available(self):
        if self._resolve_git_executable():
            return True

        self._show_git_missing_error()
        return False

    def _show_git_missing_error(self):
        QMessageBox.warning(
            self.iface.mainWindow(),
            self.TOOLBAR_NAME,
            (
                "Git konnte in QGIS nicht gefunden werden.\n\n"
                "Unter Windows liegt git.exe oft ausserhalb des PATH von QGIS. "
                "Das Plugin sucht jetzt auch in typischen Git-for-Windows-Ordnern, "
                "braucht aber eine vorhandene Git-Installation."
            ),
        )

    def _probe_repo_root(self, selected_dir):
        result = self._run_git(["-C", str(selected_dir), "rev-parse", "--show-toplevel"])
        return {
            "repo_root": result["stdout"] if result["ok"] else "",
            "error": result["error"],
        }

    def _run_git(self, arguments, cwd=None):
        git_program = self._resolve_git_executable()
        if not git_program:
            return {
                "ok": False,
                "stdout": "",
                "stderr": "",
                "returncode": None,
                "error": "missing_git",
            }

        try:
            result = subprocess.run(
                [git_program, *list(arguments)],
                cwd=cwd,
                capture_output=True,
                check=False,
                env=self._git_env(),
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "ok": False,
                "stdout": "",
                "stderr": str(exc),
                "returncode": None,
                "error": "start_failed",
            }

        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "error": "",
        }

    def _resolve_git_executable(self):
        cached_program = str(self._git_executable or "").strip()
        if cached_program and Path(cached_program).is_file():
            return cached_program

        git_program = shutil.which("git")
        if git_program:
            self._git_executable = git_program
            return git_program

        for candidate in self._windows_git_candidates():
            if candidate.is_file():
                self._git_executable = str(candidate)
                return self._git_executable

        self._git_executable = ""
        return ""

    def _windows_git_candidates(self):
        if os.name != "nt":
            return []

        candidates = []
        for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
            base_dir = str(os.environ.get(env_name) or "").strip()
            if not base_dir:
                continue
            base_path = Path(base_dir)
            candidates.extend(
                [
                    base_path / "Git" / "cmd" / "git.exe",
                    base_path / "Git" / "bin" / "git.exe",
                    base_path / "Programs" / "Git" / "cmd" / "git.exe",
                    base_path / "Programs" / "Git" / "bin" / "git.exe",
                ]
            )

        github_desktop_root = Path(str(os.environ.get("LocalAppData") or "").strip()) / "GitHubDesktop"
        if github_desktop_root.is_dir():
            for app_dir in sorted(github_desktop_root.glob("app-*"), reverse=True):
                candidates.extend(
                    [
                        app_dir / "resources" / "app" / "git" / "cmd" / "git.exe",
                        app_dir / "resources" / "app" / "git" / "bin" / "git.exe",
                    ]
                )

        home_dir = Path.home()
        candidates.extend(
            [
                home_dir / "scoop" / "shims" / "git.exe",
                home_dir / "scoop" / "apps" / "git" / "current" / "cmd" / "git.exe",
            ]
        )
        return candidates
