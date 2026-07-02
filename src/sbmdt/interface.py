from __future__ import annotations

from sbmdt.evaluator.alibaba import AlibabaEvaluator
from sbmdt.evaluator.base import PatchType, TestResult
from sbmdt.pred import Pred

__all__ = ['evaluate']


def evaluate(
    instance_id: str, patch_type: PatchType, pred: Pred | None
) -> list[TestResult]:
    if instance_id.startswith('alibaba'):
        evaluator = AlibabaEvaluator(
            instance_id=instance_id,
            patch_type=patch_type,
            agent_name=Pred.get_agent_name(pred),
            pred=pred,
        )
    elif instance_id.startswith('grommet'):
        from sbmdt.evaluator.grommet import GrommetEvaluator
        evaluator = GrommetEvaluator(
            instance_id=instance_id,
            patch_type=patch_type,
            agent_name=Pred.get_agent_name(pred),
            pred=pred,
        )
    elif instance_id.startswith('GoogleChrome'):
        from sbmdt.evaluator.lighthouse import LighthouseEvaluator
        evaluator = LighthouseEvaluator(
            instance_id=instance_id,
            patch_type=patch_type,
            agent_name=Pred.get_agent_name(pred),
            pred=pred,
        )
    elif instance_id.startswith('prettier'):
        from sbmdt.evaluator.prettier import PrettierEvaluator
        evaluator = PrettierEvaluator(
            instance_id=instance_id,
            patch_type=patch_type,
            agent_name=Pred.get_agent_name(pred),
            pred=pred,
        )
    elif instance_id.startswith('highlightjs'):
        from sbmdt.evaluator.highlightjs import HighlightjsEvaluator
        evaluator = HighlightjsEvaluator(
            instance_id=instance_id,
            patch_type=patch_type,
            agent_name=Pred.get_agent_name(pred),
            pred=pred,
        )
    else:
        raise Exception(f'unknown instance ID {instance_id}')

    return evaluator.run()
