from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .actions import MAC_APP_LAUNCHERS, _mac_app_name, _translated_launcher
from .model import ButtonConfig, Profile


PAGE_SENTINELS = {"__previous__", "__next__", "__parent__"}


@dataclass(frozen=True)
class DiagnosticIssue:
    page: str
    index: int
    label: str
    message: str

    def render(self) -> str:
        label = f" ({_short_text(self.label)})" if self.label else ""
        return f"- {self.page} button {self.index + 1}{label}: {self.message}"


@dataclass(frozen=True)
class ProfileDiagnostics:
    page_count: int
    configured_buttons: int
    action_counts: Counter[str]
    issues: tuple[DiagnosticIssue, ...]

    def short_summary(self) -> str:
        issue_count = len(self.issues)
        issue_label = "issue" if issue_count == 1 else "issues"
        return f"{self.page_count} pages, {self.configured_buttons} configured buttons, {issue_count} {issue_label}"

    def render(self) -> str:
        lines = [
            "Import report:",
            f"Pages: {self.page_count}",
            f"Configured buttons: {self.configured_buttons}",
            f"Actions: {_format_action_counts(self.action_counts)}",
        ]
        if not self.issues:
            lines.append("Issues: none found")
        else:
            lines.append(f"Issues: {len(self.issues)}")
            lines.extend(issue.render() for issue in self.issues[:12])
            if len(self.issues) > 12:
                lines.append(f"- ... {len(self.issues) - 12} more")
        return "\n".join(lines)


def profile_diagnostics(profile: Profile) -> ProfileDiagnostics:
    page_ids = profile.page_ids()
    action_counts: Counter[str] = Counter()
    configured_buttons = 0
    issues: list[DiagnosticIssue] = []

    for page_id in page_ids:
        page_name = profile.page_names.get(page_id, page_id)
        for raw_index, config in profile.pages.get(page_id, {}).items():
            if not _is_configured(config):
                continue
            configured_buttons += 1
            action_counts[config.action_type] += 1
            index = _safe_index(raw_index)
            issues.extend(_button_issues(profile, page_name, index, config))

    return ProfileDiagnostics(
        page_count=len(page_ids),
        configured_buttons=configured_buttons,
        action_counts=action_counts,
        issues=tuple(issues),
    )


def redact_target(config: ButtonConfig) -> str:
    if not config.target:
        return "-"
    if config.action_type == "text":
        return "<redacted text>"
    return config.target


def _button_issues(profile: Profile, page_name: str, index: int, config: ButtonConfig) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    target = config.target.strip()
    if config.action_type == "page":
        if not target:
            issues.append(_issue(page_name, index, config, "page action has no target"))
        elif target not in PAGE_SENTINELS and target not in profile.pages:
            issues.append(_issue(page_name, index, config, f"page target is missing: {target}"))
    elif config.action_type in {"command", "shell", "url", "file", "text", "media", "shortcut"} and not target:
        issues.append(_issue(page_name, index, config, f"{config.action_type} action has no target"))

    if config.action_type == "file" and target:
        mac_app = _mac_app_name(target)
        if mac_app:
            translated = _translated_launcher(target)
            if not translated:
                if mac_app in MAC_APP_LAUNCHERS:
                    message = f"Linux launcher is not installed for macOS app: {mac_app}"
                else:
                    message = f"macOS app needs Linux launcher mapping: {mac_app}"
                issues.append(_issue(page_name, index, config, message))
        elif not Path(target).expanduser().exists():
            issues.append(_issue(page_name, index, config, "file target does not exist on this computer"))

    if config.action_type == "none" and (config.label or config.subtitle or config.image_path):
        issues.append(_issue(page_name, index, config, "imported button has no supported action yet"))
    return issues


def _issue(page_name: str, index: int, config: ButtonConfig, message: str) -> DiagnosticIssue:
    return DiagnosticIssue(page=page_name, index=index, label=config.label, message=message)


def _is_configured(config: ButtonConfig) -> bool:
    return any((config.label, config.subtitle, config.target, config.image_path, config.action_type != "none"))


def _safe_index(raw_index: str) -> int:
    try:
        return int(raw_index)
    except ValueError:
        return 0


def _short_text(value: str, limit: int = 36) -> str:
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 3]}..."


def _format_action_counts(action_counts: Counter[str]) -> str:
    if not action_counts:
        return "none"
    return ", ".join(f"{action}={count}" for action, count in sorted(action_counts.items()))
