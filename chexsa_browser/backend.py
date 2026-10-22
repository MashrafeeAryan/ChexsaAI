"""Browser backend: a complete local observation and a compact model-facing view."""

import hashlib
import time

from .actions import Executor
from .collector import Collector
from .context import ContextView, changes
from .models import ActionResult, BrowserError, Observation
from .regions import group_regions
from .session import BrowserSession
from .targets import TargetRegistry
from .visual import VisualTargeting


class BrowserBackend:
    def __init__(self, session=None, context_budget=12000, trace_screenshots=False, **session_options):
        self.session = session or BrowserSession(**session_options)
        self.registry = TargetRegistry(self.session)
        self.collector = Collector(self.session)
        self.observation = None
        self.sequence = 0
        self.view = ContextView(context_budget)
        self.executor = Executor(self)
        self._change_counter = None
        self.visual = VisualTargeting(self)
        self.task_journal = None
        self.trace_screenshots = trace_screenshots

    def capture_screenshot(self):
        return self.visual.capture()

    def connect(self):
        self.session.connect()

    def observe(self):
        for attempt in range(3):
            self.registry.invalidate()
            page = self.session.ensure_page()
            try:
                return self._observe_page(page)
            except Exception as error:
                closed = page.is_closed() or not self.session.browser or not self.session.browser.is_connected()
                transient = isinstance(error, BrowserError) and error.code == "stale_observation" or any(message in str(error).lower() for message in ("frame with the given frameid is not found", "execution context was destroyed", "cannot find context with specified id"))
                if not closed and (not transient or attempt == 2):
                    raise
                if not closed:
                    page.wait_for_timeout(150)
        self.registry.invalidate()
        raise BrowserError("page_closed", "Chrome's tabs kept closing during observation. Open a tab and retry.")

    def _observe_page(self, page):
        page.evaluate("""() => {if(!window.__chexsaWatch){window.__chexsaWatch={version:0};const tick=()=>window.__chexsaWatch.version++;new MutationObserver(tick).observe(document,{subtree:true,childList:true,attributes:true,characterData:true});for(const event of ['input','change','scroll'])addEventListener(event,tick,true);} }""")
        before = dict(self.session.epochs)
        elements, text, issues = self.collector.collect()
        tabs = self.session.tabs()
        used_targets = {e.target_id for e in elements} | {self.session.page_id}
        if any(self.session.epochs.get(key) != before.get(key, 0) for key in used_targets):
            raise BrowserError("stale_observation", "The page navigated during observation. Observe again.")
        self.registry.bind(elements)
        self.sequence += 1
        fingerprint = hashlib.sha256(repr((page.url, [(e.identity, e.signature()) for e in elements], text)).encode()).hexdigest()
        result = Observation(f"o{self.sequence}", self.session.page_id, page.url, page.title(), tabs, elements, text, issues, fingerprint=fingerprint)
        result.regions = group_regions(elements, self.observation)
        result.changes = changes(self.observation, result)
        self.view.render(result)
        self.observation = result
        self._change_counter = page.evaluate("window.__chexsaWatch?.version")
        return result

    def execute(self, request):
        try:
            page = self.session.get_page()
            self._change_counter = page.evaluate("window.__chexsaWatch?.version")
        except BrowserError as error:
            return ActionResult(request.action, "error", str(error), error.code)
        except Exception:
            if page.is_closed():
                return ActionResult(request.action, "error", "The selected tab closed. Observe again.", "page_closed")
            raise
        return self.executor.execute(request)

    def wait_for_change(self, timeout=2.0):
        deadline = time.monotonic() + timeout
        changed_at = None
        last = self._change_counter
        while time.monotonic() < deadline:
            try:
                page = self.session.get_page()
                current = page.evaluate("window.__chexsaWatch?.version")
                if current != last:
                    last, changed_at = current, time.monotonic()
                if changed_at and time.monotonic() - changed_at >= .15:
                    self._change_counter = last
                    return
                page.wait_for_timeout(50)
            except Exception:
                return  # Navigation/detachment will be reconciled by the next observation.
        self._change_counter = last

    def close(self):
        self.registry.invalidate()
        try:
            self.session.close()
        finally:
            if self.task_journal:
                self.task_journal.close()
                self.task_journal = None
