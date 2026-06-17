"""
Abstract base class for benchmark evaluators.

Defines the lifecycle interface (setup -> evaluate -> cleanup) that all
concrete evaluators must implement, and provides the final ``cleanup``
and ``run`` orchestration methods.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import final

from docker.models.containers import Container
from docker.models.images import Image

from sbmdt.pred import Pred

__all__ = [
    'Evaluator',
    'PatchType',
    'TestResult',
]

log = logging.getLogger(__name__)


class PatchType(StrEnum):
    """The patch state under which a test was executed.

    Attributes:
        BEFORE_PATCH: Test run against the unmodified baseline.
        WITH_IMAGE: Test run with the patch applied via a custom image.
        WITHOUT_IMAGE: Test run with the patch applied without a custom image.
    """

    BEFORE_PATCH = 'before_patch'
    WITH_IMAGE = 'with_image'
    WITHOUT_IMAGE = 'without_image'


@dataclass(kw_only=True)
class TestResult:
    """Result of a single test case from a benchmark evaluation.

    Attributes:
        instance_id: Identifier of the benchmark instance that was evaluated.
        patch_type: The patch state under which the test was run.
        test_name: Name of the individual test case.
        passed: Whether the test case passed.
    """

    instance_id: str
    patch_type: PatchType
    agent_name: str
    test_name: str
    passed: bool


class Evaluator(ABC):
    """Abstract base for Docker-based benchmark evaluators.

    Subclasses must implement :meth:`setup`, :meth:`evaluate`,
    :meth:`pre_cleanup`, and :meth:`post_cleanup`. The :meth:`cleanup`
    and :meth:`run` methods are final and handle container/image teardown
    and overall orchestration respectively.

    Attributes:
        image: The Docker image built or used by this evaluator.
        container: The running Docker container managed by this evaluator.
        patch_type: The patch state this evaluator is running under.
            Determines whether :meth:`run` calls :meth:`apply_patch`.
        pred: The model-generated patch to apply, or ``None`` when
            ``patch_type`` is :attr:`PatchType.BEFORE_PATCH`.
    """

    image: Image | None
    container: Container | None
    patch_type: PatchType
    pred: Pred | None

    @abstractmethod
    def setup(self) -> None:
        """Build the image and start the container.

        Implementations should assign ``self.image`` and ``self.container``.
        """
        ...

    @abstractmethod
    def apply_patch(self) -> None:
        """Apply ``self.pred``'s patch to the evaluation environment.

        Called by :meth:`run` after :meth:`setup` and before
        :meth:`evaluate`, but only when ``self.patch_type`` is not
        :attr:`PatchType.BEFORE_PATCH`; when there is no patch to apply,
        :meth:`run` skips calling this method entirely. ``self.pred`` is
        therefore guaranteed to be set whenever this is called.

        ``PatchType.WITH_IMAGE`` and ``PatchType.WITHOUT_IMAGE`` only
        describe how the resulting :class:`TestResult` should be
        interpreted during analysis; they do not change how the patch
        itself is applied here.

        Raises:
            Exception: If the patch fails to apply cleanly.
        """
        ...

    @abstractmethod
    def evaluate(self) -> list[TestResult]:
        """Execute the benchmark and collect results.

        Returns:
            A list of :class:`TestResult` from the evaluation run.
        """
        ...

    @abstractmethod
    def pre_cleanup(self) -> None:
        """Hook called before container/image teardown.

        Runs inside a try/except in :meth:`cleanup`; exceptions are logged
        but do not abort cleanup.
        """
        ...

    @abstractmethod
    def post_cleanup(self) -> None:
        """Hook called after container/image teardown.

        Runs inside a try/except in :meth:`cleanup`; exceptions are logged
        but do not abort cleanup.
        """
        ...

    @final
    def cleanup(self):
        """Stop and remove the container and image.

        Calls :meth:`pre_cleanup` first and :meth:`post_cleanup` last.
        Each step is wrapped in its own try/except so a failure in one
        step does not prevent the remaining steps from running.
        """

        try:
            self.pre_cleanup()
        except Exception:
            log.error('Error running pre-cleanup hook')

        if self.container:
            try:
                log.info(f'Stopping container {self.container.name}')
                self.container.stop()
                log.info(f'Stopped container {self.container.name}')
            except Exception as e:
                log.error(f'Failed to stop container: {e}')
            try:
                log.info(f'Removing container {self.container.name}')
                self.container.remove()
                log.info(f'Removed container {self.container.name}')
            except Exception as e:
                log.error(f'Failed to remove container: {e}')
        else:
            log.warning('Container did not exist')

        if self.image:
            try:
                log.info(f'Removing image {self.image.tags}')
                self.image.remove()
                log.info(f'Removed image {self.image.tags}')
            except Exception as e:
                log.error(f'Failed to remove image: {e}')
        else:
            log.warning('Image did not exist')

        try:
            self.post_cleanup()
        except Exception:
            log.error('Error running post-cleanup hook')

    @final
    def run(self) -> list[TestResult]:
        """Run the full evaluation lifecycle.

        Stages: :meth:`setup`, then :meth:`apply_patch` (only when
        ``self.patch_type`` is not :attr:`PatchType.BEFORE_PATCH`), then
        :meth:`evaluate`, then :meth:`cleanup`.
        """
        self.setup()
        if self.patch_type != PatchType.BEFORE_PATCH:
            self.apply_patch()
        results = self.evaluate()
        self.cleanup()
        return results
