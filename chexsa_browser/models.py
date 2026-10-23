"""Shared browser/task contracts. Browser identities never come from model text."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Element:
    target_id: str
    frame_id: str
    document_id: str
    node_id: int
    role: str
    name: str
    parent: str | None = None
    value: str = ""
    states: dict[str, Any] = field(default_factory=dict)
    capabilities: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    bounds: tuple[float, ...] = ()
    ref: str = ""
    region: str = ""
    region_path: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        return f"{self.target_id}/{self.frame_id}/{self.document_id}/{self.node_id}"

    def signature(self) -> tuple:
        return self.role, self.name, self.value, repr(sorted(self.states.items())), self.context


@dataclass
class Region:
    key: str
    label: str
    elements: list[Element] = field(default_factory=list)
    priority: int = 0
    ref: str = "page"


@dataclass
class Observation:
    id: str
    page_id: str
    url: str
    title: str
    tabs: list[dict[str, Any]]
    elements: list[Element]
    text: dict[str, Any]
    issues: list[str] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    context: str = ""
    changes: list[str] = field(default_factory=list)
    screenshot: bytes = b""
    screenshot_id: str = ""
    fingerprint: str = ""


@dataclass
class ActionRequest:
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionResult:
    action: str
    status: str
    message: str = ""
    code: str = ""
    executed: bool = False
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskSpec:
    goal: str
    inputs: dict[str, str] = field(default_factory=dict)
    subgoals: list[str] = field(default_factory=list)
    completion: list[str] = field(default_factory=list)
    intent: str = "act"


@dataclass
class TaskState:
    id: str
    spec: TaskSpec
    status: str = "running"
    progress: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    submission: str = "none"
    steps: int = 0
    failures: int = 0
    question: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    commit_baseline: str = ""
    email_checked: bool = False
    result_message: str = ""
    commit_image_hash: str = ""
    commit_page_id: str = ""
    commit_frame_id: str = ""


@dataclass
class TaskResult:
    status: str
    message: str
    task_id: str


class Backend(Protocol):
    def observe(self) -> Observation: ...
    def execute(self, request: ActionRequest) -> ActionResult: ...
    def wait_for_change(self, timeout: float = 2.0) -> None: ...
    def close(self) -> None: ...


class BrowserError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
