from typing import Any, Dict, Optional


class BaseExporter:
    def export(
        self,
        project_name: str,
        base_folder: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError
