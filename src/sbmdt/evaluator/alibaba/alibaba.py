"""
Evaluator implementation for Alibaba repository instances.

Builds a Docker image from the instance's Dockerfile, configures the Karma
test runner to emit JUnit XML output, runs the test suite, and retrieves
the results.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, override

import docker

from sbmdt.env import DOCKERFILES_BASE
from sbmdt.evaluator.alibaba.karma_junit_parser import (
    results_xml_to_test_results,
)
from sbmdt.evaluator.base import Evaluator, PatchType, TestResult
from sbmdt.pred import Pred
from sbmdt.utils import apply_change, read_from_container, write_to_container

__all__ = [
    'AlibabaEvaluator',
]

log = logging.getLogger(__name__)

KARMA_FILE: Final[str] = '/testbed/scripts/test/karma.js'
PATCH_FILE: Final[str] = '/tmp/model.patch'


class AlibabaEvaluator(Evaluator):
    """Evaluator for Alibaba benchmark instances.

    Builds a Docker image for the given instance, patches the Karma
    configuration to produce JUnit XML output, executes ``npm test``,
    and reads the resulting XML from the container.
    """

    instance_id: str
    dockerfile_path: Path
    patch_type: PatchType
    agent_name: str
    pred: Pred | None

    def __init__(
        self,
        instance_id: str,
        patch_type: PatchType,
        agent_name: str,
        pred: Pred | None,
    ):
        """Initialize the evaluator for the given instance.

        Args:
            instance_id: Identifier for the benchmark instance. Used to
                locate the Dockerfile under ``DOCKERFILES_BASE`` and to
                name the resulting image and container.
        """
        self.instance_id = instance_id
        self.dockerfile_path = DOCKERFILES_BASE / instance_id / 'Dockerfile'
        self.patch_type = patch_type
        self.agent_name = agent_name
        self.pred = pred
        self.image = None
        self.container = None

    @override
    def setup(self) -> None:
        """Build the Docker image, start the container, and patch Karma.

        Steps performed:
        1. Build the image from the instance's Dockerfile.
        2. Start the container in detached mode with a TTY.
        3. Install ``karma-junit-reporter`` in the container.
        4. Patch ``karma.js`` to add the JUnit reporter, its config block,
           and the plugin entry.
        """

        client = docker.from_env()
        self.image, _ = client.images.build(
            path=str(self.dockerfile_path.parent.resolve()),
            tag=f'sbmdt-{self.instance_id}:latest',
        )
        self.container = client.containers.run(
            self.image,
            command='/bin/bash',
            name=f'sbmdt-{self.instance_id}',
            stdin_open=True,
            tty=True,
            detach=True,
        )

        # 1. Install package
        exit_code, output = self.container.exec_run(
            'npm install karma-junit-reporter --save-dev',
            workdir='/testbed',
            stream=False,
        )
        assert isinstance(output, bytes)

        log.info(exit_code)
        log.info(output.decode())

        # 2. Add junit to reporters
        apply_change(
            container=self.container,
            file=KARMA_FILE,
            find="reporters: ['spec', 'coverage']",
            replace="reporters: ['spec', 'coverage', 'junit']",
            assertion="reporters: ['spec', 'coverage', 'junit']",
        )

        # 3. Add junitReporter config
        apply_change(
            container=self.container,
            file=KARMA_FILE,
            find="hostname: 'localhost'",
            replace="""junitReporter: {
                    outputDir: 'test-results',
                    outputFile: 'results.xml',
                    useBrowserName: false,
                },
                hostname: 'localhost'""",
            assertion='junitReporter:',
        )

        # 4. Add plugin
        apply_change(
            container=self.container,
            file=KARMA_FILE,
            find="'karma-coverage',",
            replace="'karma-coverage',\n            'karma-junit-reporter',",
            assertion="'karma-junit-reporter',",
        )

        log.info('All changes applied successfully.')

    @override
    def apply_patch(self) -> None:
        """Apply ``self.pred.model_patch`` to ``/testbed`` via ``git apply``.

        Writes the patch to a temporary file inside the container and
        runs ``git apply`` against it from ``/testbed``.

        Raises:
            Exception: If the container has not been started, or if
                ``git apply`` exits non-zero.
        """

        if self.container is None:
            raise Exception('no container')
        assert self.pred is not None

        write_to_container(self.container, PATCH_FILE, self.pred.model_patch)

        exit_code, output = self.container.exec_run(
            f'git apply {PATCH_FILE}',
            workdir='/testbed',
            stream=False,
        )
        assert isinstance(output, bytes)

        log.info(exit_code)
        log.info(output.decode())

        if exit_code != 0:
            raise Exception(
                f'Failed to apply patch for {self.instance_id}: '
                f'{output.decode()}'
            )

    @override
    def evaluate(self) -> list[TestResult]:
        """Run ``npm test`` and retrieve the JUnit XML results.

        Returns:
            A list of :class:`TestResult` parsed from the JUnit XML output.

        Raises:
            Exception: If the container has not been started (i.e., ``setup``
                was not called first).
        """

        if self.container is None:
            raise Exception('no container')

        exit_code, output = self.container.exec_run(
            'npm test',
            environment={'TRAVIS': 'true'},
            workdir='/testbed',
            stream=False,
        )
        log.info('done running')
        assert isinstance(output, bytes)

        log.info(exit_code)
        log.info(output.decode())
        results = read_from_container(
            self.container, '/testbed/scripts/test/test-results/results.xml'
        )

        return results_xml_to_test_results(
            self.instance_id,
            self.patch_type,
            self.agent_name,
            results,
        )

    @override
    def pre_cleanup(self) -> None:
        """Pre-cleanup hook. No-op for this evaluator."""
        pass

    @override
    def post_cleanup(self) -> None:
        """Post-cleanup hook. No-op for this evaluator."""
        pass
