import os
import subprocess

from qgis.PyQt.QtCore import QProcess, QProcessEnvironment
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import Qgis, QgsProject


class TrassifyGithubDialog(QDialog):
    WINDOW_TITLE = "Trassify Github"
    LOG_TAG = "Trassify Github"

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.repo_root = ""
        self.origin_url = ""
        self.current_command = ""
        self.process = None

        self.setWindowTitle(self.WINDOW_TITLE)
        self.resize(760, 460)

        self._build_ui()
        self._update_repo_state(False)
        self.command_status_label.setText("Bitte einen Ordner auswaehlen.")

    def shutdown(self):
        if self._command_running():
            self.process.kill()
            self.process.waitForFinished(2000)
            self._cleanup_process()
        self.close()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info_label = QLabel(
            "Waehlt einen lokalen Ordner aus. "
            "Wenn ein Git-Repository erkannt wird, werden die Shell-Befehle "
            "'git pull' und 'git push' direkt ausgefuehrt."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        path_layout = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Noch kein Ordner ausgewaehlt")
        path_layout.addWidget(self.path_edit)

        self.choose_button = QPushButton("Ordner waehlen", self)
        self.choose_button.clicked.connect(self._select_directory)
        path_layout.addWidget(self.choose_button)
        layout.addLayout(path_layout)

        self.repo_status_label = QLabel(self)
        self.repo_status_label.setWordWrap(True)
        layout.addWidget(self.repo_status_label)

        self.repo_details_label = QLabel(self)
        self.repo_details_label.setWordWrap(True)
        self.repo_details_label.setTextInteractionFlags(self.repo_details_label.textInteractionFlags())
        layout.addWidget(self.repo_details_label)

        actions_layout = QHBoxLayout()

        self.pull_button = QPushButton("Git Pull", self)
        self.pull_button.clicked.connect(lambda: self._run_git_command("pull"))
        actions_layout.addWidget(self.pull_button)

        self.push_button = QPushButton("Git Push", self)
        self.push_button.clicked.connect(lambda: self._run_git_command("push"))
        actions_layout.addWidget(self.push_button)

        layout.addLayout(actions_layout)

        self.command_status_label = QLabel(self)
        self.command_status_label.setWordWrap(True)
        layout.addWidget(self.command_status_label)

        self.log_output = QPlainTextEdit(self)
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.log_output, 1)

    def _select_directory(self):
        start_dir = self.repo_root or self.path_edit.text() or self._default_start_directory()
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Ordner waehlen",
            start_dir,
            QFileDialog.ShowDirsOnly,
        )
        if not selected_dir:
            return

        self.path_edit.setText(selected_dir)
        self._inspect_directory(selected_dir, write_log=True)

    def _default_start_directory(self):
        project_home = QgsProject.instance().homePath()
        if project_home:
            return project_home
        return os.path.expanduser("~")

    def _inspect_directory(self, selected_dir, write_log):
        repo_root = self._detect_repo_root(selected_dir)
        self.repo_root = repo_root or ""
        self.origin_url = ""

        if not self.repo_root:
            self.repo_status_label.setText("Kein Git-Repository erkannt.")
            self.repo_details_label.setText(
                "Im gewaehlten Ordner wurde kein Git-Repository gefunden."
            )
            self._update_repo_state(False)
            if write_log:
                self.command_status_label.setText(
                    "Bitte einen Ordner mit Git-Repository auswaehlen."
                )
            if write_log:
                self._append_log(
                    "$ repo-check: {path}\nKein Git-Repository erkannt.\n\n".format(
                        path=selected_dir
                    )
                )
            return

        self.origin_url = self._read_git_output(
            ["git", "-C", self.repo_root, "remote", "get-url", "origin"]
        )
        branch_name = self._read_git_output(
            ["git", "-C", self.repo_root, "branch", "--show-current"]
        )

        repo_kind = "Git-Repository erkannt."
        if self.origin_url and "github.com" in self.origin_url.lower():
            repo_kind = "GitHub-Repository erkannt."

        details = ["Repo root: {path}".format(path=self.repo_root)]
        if branch_name:
            details.append("Branch: {branch}".format(branch=branch_name))
        if self.origin_url:
            details.append("Origin: {origin}".format(origin=self.origin_url))

        self.repo_status_label.setText(repo_kind)
        self.repo_details_label.setText("\n".join(details))
        self._update_repo_state(True)
        if write_log:
            self.command_status_label.setText(
                "Repository bereit. Git Pull oder Git Push kann gestartet werden."
            )

        if write_log:
            self._append_log(
                "$ repo-check: {path}\n{kind}\n{details}\n\n".format(
                    path=selected_dir,
                    kind=repo_kind,
                    details="\n".join(details),
                )
            )

    def _detect_repo_root(self, selected_dir):
        try:
            result = subprocess.run(
                ["git", "-C", selected_dir, "rev-parse", "--show-toplevel"],
                capture_output=True,
                check=False,
                env=self._git_env(),
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._report_git_lookup_error(exc)
            return None

        if result.returncode != 0:
            return None

        repo_root = result.stdout.strip()
        return repo_root or None

    def _read_git_output(self, command):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                env=self._git_env(),
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ""

        if result.returncode != 0:
            return ""

        return result.stdout.strip()

    def _git_env(self):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def _run_git_command(self, subcommand):
        if not self.repo_root:
            QMessageBox.warning(
                self,
                self.WINDOW_TITLE,
                "Bitte zuerst einen Ordner mit Git-Repository auswaehlen.",
            )
            return

        if self._command_running():
            return

        self.current_command = "git {subcommand}".format(subcommand=subcommand)
        self.command_status_label.setText(
            "Fuehre '{command}' in '{path}' aus ...".format(
                command=self.current_command,
                path=self.repo_root,
            )
        )
        self._append_log(
            "$ {command}\n".format(command=self.current_command)
        )

        self.process = QProcess(self)
        self.process.setWorkingDirectory(self.repo_root)
        self.process.setProgram("git")
        self.process.setArguments([subcommand])

        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("GIT_TERMINAL_PROMPT", "0")
        self.process.setProcessEnvironment(environment)

        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._command_error)
        self.process.finished.connect(self._command_finished)

        self._update_running_state(True)
        self.process.start()

    def _read_stdout(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._append_log(text)

    def _read_stderr(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self._append_log(text)

    def _command_error(self, error):
        if error != QProcess.FailedToStart:
            return

        self.command_status_label.setText(
            "Git konnte nicht gestartet werden. Ist Git im Systempfad verfuegbar?"
        )
        self.iface.messageBar().pushMessage(
            self.LOG_TAG,
            "Git konnte nicht gestartet werden.",
            level=Qgis.Critical,
            duration=6,
        )
        self._append_log("Git konnte nicht gestartet werden.\n\n")
        self._cleanup_process()
        self._update_running_state(False)

    def _command_finished(self, exit_code, exit_status):
        self._read_stdout()
        self._read_stderr()

        command_text = self.current_command or "git"
        if exit_status == QProcess.NormalExit and exit_code == 0:
            self.command_status_label.setText(
                "'{command}' erfolgreich abgeschlossen.".format(command=command_text)
            )
            self.iface.messageBar().pushMessage(
                self.LOG_TAG,
                "{command} erfolgreich.".format(command=command_text),
                level=Qgis.Success,
                duration=4,
            )
            self._append_log("[ok] {command}\n\n".format(command=command_text))
        else:
            self.command_status_label.setText(
                "'{command}' wurde mit Exit-Code {code} beendet.".format(
                    command=command_text,
                    code=exit_code,
                )
            )
            self.iface.messageBar().pushMessage(
                self.LOG_TAG,
                "{command} fehlgeschlagen. Details stehen im Protokoll.".format(
                    command=command_text
                ),
                level=Qgis.Warning,
                duration=6,
            )
            self._append_log(
                "[error] {command} (Exit-Code {code})\n\n".format(
                    command=command_text,
                    code=exit_code,
                )
            )

        selected_dir = self.path_edit.text()
        self._cleanup_process()
        self._update_running_state(False)
        if selected_dir:
            self._inspect_directory(selected_dir, write_log=False)

    def _update_repo_state(self, has_repo):
        enable_actions = has_repo and not self._command_running()
        self.pull_button.setEnabled(enable_actions)
        self.push_button.setEnabled(enable_actions)

    def _update_running_state(self, is_running):
        self.choose_button.setEnabled(not is_running)
        self.pull_button.setEnabled(False if is_running else bool(self.repo_root))
        self.push_button.setEnabled(False if is_running else bool(self.repo_root))

    def _command_running(self):
        return self.process is not None and self.process.state() != QProcess.NotRunning

    def _cleanup_process(self):
        if self.process is None:
            self.current_command = ""
            return

        self.process.deleteLater()
        self.process = None
        self.current_command = ""

    def _append_log(self, text):
        if not text:
            return

        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.log_output.setTextCursor(cursor)
        self.log_output.ensureCursorVisible()

    def _report_git_lookup_error(self, exc):
        self.command_status_label.setText("Git konnte nicht gefunden oder ausgefuehrt werden.")
        self.iface.messageBar().pushMessage(
            self.LOG_TAG,
            "Git konnte nicht gefunden oder ausgefuehrt werden.",
            level=Qgis.Warning,
            duration=6,
        )
        self._append_log("Git-Fehler bei der Repo-Erkennung: {error}\n\n".format(error=exc))
