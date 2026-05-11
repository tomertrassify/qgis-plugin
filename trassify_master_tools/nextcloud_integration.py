from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.core import Qgis

from .i18n import tr
from .shared_settings import (
    DEFAULT_NEXTCLOUD_CATALOG_ROOT,
    LEGACY_NEXTCLOUD_CATALOG_ROOTS,
)


LOGIN_FLOW_POLL_INTERVAL_MS = 2000


class NextcloudApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = int(status_code or 0)


@dataclass
class NextcloudUserProfile:
    user_id: str = ""
    login_name: str = ""
    display_name: str = ""
    email: str = ""
    groups: list[str] = field(default_factory=list)


def normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def normalize_remote_path(value: str) -> str:
    parts = [
        segment.strip()
        for segment in str(value or "").replace("\\", "/").split("/")
        if segment.strip()
    ]
    return "/".join(parts)


class NextcloudApiClient:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent

    def start_login_flow_v2(self, base_url: str) -> dict:
        url = f"{normalize_base_url(base_url)}/index.php/login/v2"
        request = urllib.request.Request(
            url,
            method="POST",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
            data=b"",
        )
        return self._read_json_response(request)

    def poll_login_flow_v2(self, poll_endpoint: str, poll_token: str) -> dict | None:
        payload = urllib.parse.urlencode({"token": str(poll_token or "")}).encode("utf-8")
        request = urllib.request.Request(
            str(poll_endpoint or "").strip(),
            method="POST",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=payload,
        )
        try:
            return self._read_json_response(request)
        except NextcloudApiError as exc:
            if exc.status_code == 404:
                return None
            raise

    def fetch_current_user(
        self, base_url: str, login_name: str, app_password: str
    ) -> NextcloudUserProfile:
        request = urllib.request.Request(
            f"{normalize_base_url(base_url)}/ocs/v1.php/cloud/user?format=json",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "OCS-APIRequest": "true",
                "Authorization": self._basic_auth_header(login_name, app_password),
            },
        )
        payload = self._read_json_response(request)
        data = dict(payload.get("ocs", {}).get("data") or {})
        groups = data.get("groups") or []
        if not isinstance(groups, list):
            groups = []

        return NextcloudUserProfile(
            user_id=str(data.get("id") or data.get("user_id") or "").strip(),
            login_name=str(login_name or "").strip(),
            display_name=str(
                data.get("display-name")
                or data.get("displayname")
                or data.get("displayName")
                or data.get("id")
                or login_name
                or ""
            ).strip(),
            email=str(data.get("email") or "").strip(),
            groups=[str(group).strip() for group in groups if str(group).strip()],
        )

    def revoke_current_app_password(
        self, base_url: str, login_name: str, app_password: str
    ) -> None:
        request = urllib.request.Request(
            f"{normalize_base_url(base_url)}/ocs/v2.php/core/apppassword",
            method="DELETE",
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "OCS-APIRequest": "true",
                "Authorization": self._basic_auth_header(login_name, app_password),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response.read()
        except urllib.error.HTTPError:
            # The local session should still be removed even if the remote revoke fails.
            return
        except urllib.error.URLError:
            return

    def load_catalog(
        self,
        base_url: str,
        login_name: str,
        app_password: str,
        catalog_root: str,
        webdav_user: str = "",
    ) -> dict:
        raw = self.read_remote_file(
            base_url,
            login_name,
            app_password,
            f"{normalize_remote_path(catalog_root)}/catalog/plugins.json",
            webdav_user=webdav_user,
        )
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise NextcloudApiError(
                f"catalog/plugins.json konnte nicht gelesen werden: {exc}"
            ) from exc

    def download_remote_file(
        self,
        base_url: str,
        login_name: str,
        app_password: str,
        remote_path: str,
        destination_path,
        webdav_user: str = "",
    ) -> None:
        destination_path.write_bytes(
            self.read_remote_file(
                base_url,
                login_name,
                app_password,
                remote_path,
                webdav_user=webdav_user,
            )
        )

    def read_remote_file(
        self,
        base_url: str,
        login_name: str,
        app_password: str,
        remote_path: str,
        webdav_user: str = "",
    ) -> bytes:
        url = self._webdav_url(
            base_url,
            webdav_user or login_name,
            remote_path,
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Authorization": self._basic_auth_header(login_name, app_password),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace").strip() or str(exc)
            raise NextcloudApiError(message, status_code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise NextcloudApiError(str(exc.reason or exc)) from exc

    def _read_json_response(self, request: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace").strip() or str(exc)
            raise NextcloudApiError(message, status_code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise NextcloudApiError(str(exc.reason or exc)) from exc
        except json.JSONDecodeError as exc:
            raise NextcloudApiError(f"Unerwartete Antwort: {exc}") from exc

    def _webdav_url(self, base_url: str, login_name: str, remote_path: str) -> str:
        path_segments = [
            urllib.parse.quote(segment, safe="")
            for segment in normalize_remote_path(remote_path).split("/")
            if segment
        ]
        quoted_login = urllib.parse.quote(str(login_name or "").strip(), safe="")
        return (
            f"{normalize_base_url(base_url)}/remote.php/dav/files/{quoted_login}/"
            + "/".join(path_segments)
        )

    def _basic_auth_header(self, login_name: str, app_password: str) -> str:
        token = base64.b64encode(
            f"{str(login_name or '').strip()}:{str(app_password or '').strip()}".encode(
                "utf-8"
            )
        ).decode("ascii")
        return f"Basic {token}"


class NextcloudAuthManager(QObject):
    state_changed = pyqtSignal()

    def __init__(
        self,
        settings_loader,
        settings_saver,
        message_callback,
        user_agent: str,
        language_getter=None,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_loader = settings_loader
        self._settings_saver = settings_saver
        self._message_callback = message_callback
        self._language_getter = language_getter or (lambda: "de")
        self._api = NextcloudApiClient(user_agent)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(LOGIN_FLOW_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_login_flow_v2)

        self._status = "anonymous"
        self._status_detail = self._tr("nextcloud.not_logged_in")
        self._base_url = ""
        self._catalog_root = ""
        self._login_name = ""
        self._app_password = ""
        self._poll_endpoint = ""
        self._poll_token = ""
        self._profile = NextcloudUserProfile()
        self._reload_from_settings()

    @property
    def status(self) -> str:
        return self._status

    @property
    def status_detail(self) -> str:
        return self._status_detail

    @property
    def login_name(self) -> str:
        return self._login_name

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def catalog_root(self) -> str:
        return self._catalog_root

    @property
    def user_profile(self) -> NextcloudUserProfile:
        return self._profile

    def is_authorized(self) -> bool:
        return self._status == "authorized"

    def has_saved_credentials(self) -> bool:
        return bool(self._login_name and self._app_password)

    def is_authorizing(self) -> bool:
        return self._status == "authorizing"

    def retranslate_state(self) -> None:
        detail = self._translated_detail_for_state()
        if detail is None:
            return
        self._status_detail = str(detail or "").strip()

    def refresh_session(self, announce: bool = False) -> bool:
        self._reload_from_settings()
        if not self._base_url:
            self._set_state("error", self._tr("nextcloud.missing_url"))
            return False
        if not self._login_name or not self._app_password:
            self._profile = NextcloudUserProfile()
            self._set_state("anonymous", self._tr("nextcloud.not_logged_in"))
            return False

        try:
            self._profile = self._api.fetch_current_user(
                self._base_url,
                self._login_name,
                self._app_password,
            )
            detail = self._tr(
                "nextcloud.logged_in_as",
                account=self._profile.display_name or self._login_name,
            )
            if self._profile.groups:
                detail += " " + self._tr(
                    "nextcloud.groups_suffix",
                    groups=", ".join(self._profile.groups),
                )
            self._set_state("authorized", detail)
            if announce:
                self._message_callback(
                    self._tr("nextcloud.connection_updated"),
                    Qgis.Success,
                    4,
                )
            return True
        except NextcloudApiError as exc:
            if exc.status_code in {401, 403}:
                self._clear_saved_credentials()
                self._profile = NextcloudUserProfile()
                self._set_state(
                    "anonymous",
                    self._tr("nextcloud.login_invalid"),
                )
            else:
                self._profile = NextcloudUserProfile()
                self._set_state(
                    "error",
                    self._tr("nextcloud.unreachable", error=exc),
                )
            if announce:
                self._message_callback(
                    self._status_detail,
                    Qgis.Warning,
                    6,
                )
            return False

    def begin_login(self) -> bool:
        self._reload_from_settings()
        if not self._base_url:
            self._set_state("error", self._tr("nextcloud.missing_url"))
            self._message_callback(self._status_detail, Qgis.Warning, 6)
            return False

        try:
            flow_data = self._api.start_login_flow_v2(self._base_url)
            poll = dict(flow_data.get("poll") or {})
            self._poll_token = str(poll.get("token") or "").strip()
            self._poll_endpoint = str(poll.get("endpoint") or "").strip()
            login_url = str(flow_data.get("login") or "").strip()
            if not self._poll_token or not self._poll_endpoint or not login_url:
                raise NextcloudApiError(self._tr("nextcloud.login_flow_incomplete"))

            self._set_state(
                "authorizing",
                self._tr("nextcloud.login_browser_opened"),
            )
            self._poll_timer.start()
            QDesktopServices.openUrl(QUrl(login_url))
            return True
        except NextcloudApiError as exc:
            self._set_state("error", self._tr("nextcloud.login_start_failed", error=exc))
            self._message_callback(self._status_detail, Qgis.Warning, 6)
            return False

    def logout(self, revoke_remote: bool = True) -> None:
        self._poll_timer.stop()
        if revoke_remote and self._base_url and self._login_name and self._app_password:
            self._api.revoke_current_app_password(
                self._base_url,
                self._login_name,
                self._app_password,
            )
        self._clear_saved_credentials()
        self._profile = NextcloudUserProfile()
        self._poll_endpoint = ""
        self._poll_token = ""
        self._set_state("anonymous", self._tr("nextcloud.login_removed"))
        self._message_callback(self._tr("nextcloud.login_removed"), Qgis.Info, 4)

    def load_secure_catalog(self) -> dict:
        if not self.is_authorized():
            raise NextcloudApiError(self._tr("nextcloud.login_required"))
        if not self._catalog_root:
            raise NextcloudApiError(
                self._tr("nextcloud.missing_catalog_root")
            )
        attempted_roots = self._catalog_root_candidates()
        last_error = None

        for catalog_root in attempted_roots:
            try:
                payload = self._api.load_catalog(
                    self._base_url,
                    self._login_name,
                    self._app_password,
                    catalog_root,
                    webdav_user=self._profile.user_id or self._login_name,
                )
                if catalog_root != self._catalog_root:
                    self._save_catalog_root(catalog_root)
                return payload
            except NextcloudApiError as exc:
                last_error = exc
                if exc.status_code != 404:
                    raise

        attempted_text = ", ".join(attempted_roots)
        if last_error is None:
            raise NextcloudApiError(self._tr("nextcloud.catalog_load_failed"))
        raise NextcloudApiError(
            self._tr(
                "nextcloud.catalog_not_found",
                attempted=attempted_text,
                error=last_error,
            ),
            status_code=last_error.status_code,
        )

    def download_remote_file(self, remote_path: str, destination_path) -> None:
        if not self.is_authorized():
            raise NextcloudApiError(self._tr("nextcloud.login_required"))
        attempted_paths = self._download_path_candidates(remote_path)
        last_error = None

        for candidate_path in attempted_paths:
            try:
                self._api.download_remote_file(
                    self._base_url,
                    self._login_name,
                    self._app_password,
                    candidate_path,
                    destination_path,
                    webdav_user=self._profile.user_id or self._login_name,
                )
                return
            except NextcloudApiError as exc:
                last_error = exc
                if exc.status_code != 404:
                    raise

        attempted_text = ", ".join(attempted_paths)
        if last_error is None:
            raise NextcloudApiError(self._tr("nextcloud.package_load_failed"))
        raise NextcloudApiError(
            self._tr(
                "nextcloud.package_not_found",
                attempted=attempted_text,
                error=last_error,
            ),
            status_code=last_error.status_code,
        )

    def cleanup(self) -> None:
        self._poll_timer.stop()
        self._poll_endpoint = ""
        self._poll_token = ""

    def _poll_login_flow_v2(self) -> None:
        try:
            result = self._api.poll_login_flow_v2(self._poll_endpoint, self._poll_token)
            if result is None:
                return

            self._poll_timer.stop()
            settings = dict(self._settings_loader() or {})
            settings["nextcloud_base_url"] = normalize_base_url(
                str(result.get("server") or self._base_url or "").strip()
            )
            settings["nextcloud_user"] = str(result.get("loginName") or "").strip()
            settings["nextcloud_app_password"] = str(result.get("appPassword") or "").strip()
            self._settings_saver(settings)
            self.refresh_session(announce=True)
        except NextcloudApiError as exc:
            self._poll_timer.stop()
            self._set_state("error", self._tr("nextcloud.login_aborted", error=exc))
            self._message_callback(self._status_detail, Qgis.Warning, 6)

    def _reload_from_settings(self) -> None:
        settings = dict(self._settings_loader() or {})
        self._base_url = normalize_base_url(settings.get("nextcloud_base_url", ""))
        self._catalog_root = normalize_remote_path(
            settings.get("nextcloud_catalog_root", "")
        )
        self._login_name = str(settings.get("nextcloud_user", "") or "").strip()
        self._app_password = str(settings.get("nextcloud_app_password", "") or "").strip()
        if self._status not in {"authorized", "authorizing"}:
            if self._login_name and self._app_password:
                self._status = "saved"
                self._status_detail = self._tr(
                    "nextcloud.saved_login_found",
                    login=self._login_name,
                )
            else:
                self._status = "anonymous"
                self._status_detail = self._tr("nextcloud.not_logged_in")

    def _clear_saved_credentials(self) -> None:
        settings = dict(self._settings_loader() or {})
        settings["nextcloud_user"] = ""
        settings["nextcloud_app_password"] = ""
        self._settings_saver(settings)
        self._reload_from_settings()

    def _catalog_root_candidates(self) -> list[str]:
        candidates = []

        def add(root: str) -> None:
            normalized = normalize_remote_path(root)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        configured_root = normalize_remote_path(self._catalog_root)
        add(configured_root)

        if not configured_root or configured_root in LEGACY_NEXTCLOUD_CATALOG_ROOTS:
            add(DEFAULT_NEXTCLOUD_CATALOG_ROOT)
            add("nextcloud-master-catalog")

        return candidates

    def _download_path_candidates(self, remote_path: str) -> list[str]:
        candidates = []

        def add(path: str) -> None:
            normalized = normalize_remote_path(path)
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        normalized_path = normalize_remote_path(remote_path)
        catalog_root = normalize_remote_path(self._catalog_root)

        if catalog_root and normalized_path:
            if (
                normalized_path != catalog_root
                and not normalized_path.startswith(catalog_root + "/")
            ):
                add(f"{catalog_root}/{normalized_path}")

        add(normalized_path)
        return candidates

    def _save_catalog_root(self, catalog_root: str) -> None:
        normalized = normalize_remote_path(catalog_root)
        if not normalized or normalized == self._catalog_root:
            return

        settings = dict(self._settings_loader() or {})
        settings["nextcloud_catalog_root"] = normalized
        self._settings_saver(settings)
        self._catalog_root = normalized

    def _set_state(self, status: str, detail: str) -> None:
        changed = self._status != status or self._status_detail != detail
        self._status = status
        self._status_detail = str(detail or "").strip()
        if changed:
            self.state_changed.emit()

    def _translated_detail_for_state(self) -> str | None:
        if self._status == "anonymous":
            return self._tr("nextcloud.not_logged_in")
        if self._status == "saved" and self._login_name:
            return self._tr("nextcloud.saved_login_found", login=self._login_name)
        if self._status == "authorized":
            detail = self._tr(
                "nextcloud.logged_in_as",
                account=self._profile.display_name or self._login_name,
            )
            if self._profile.groups:
                detail += " " + self._tr(
                    "nextcloud.groups_suffix",
                    groups=", ".join(self._profile.groups),
                )
            return detail
        if self._status == "authorizing":
            return self._tr("nextcloud.login_browser_opened")
        return None

    def _tr(self, key: str, **kwargs) -> str:
        return tr(self._language_getter(), key, **kwargs)
