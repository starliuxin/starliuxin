from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(Exception):
    def __init__(self, message: str, *, remaining: int) -> None:
        super().__init__(message)
        self.remaining = remaining


@dataclass(frozen=True)
class BudgetReservation:
    max_output_tokens: int
    estimated_input_tokens: int


class BudgetGuard:
    MAX_RESPONSE_TOKENS = 2_048

    @staticmethod
    def reserve(*, budget: int, spent: int, prompt: str) -> BudgetReservation:
        remaining = budget - spent
        # UTF-8 bytes are a conservative cross-provider upper estimate for the input.
        estimated_input = len(prompt.encode("utf-8"))
        output_limit = min(BudgetGuard.MAX_RESPONSE_TOKENS, remaining - estimated_input)
        if output_limit < 1:
            raise BudgetExceeded(
                "当前 token 预算不足以安全发起下一次模型调用；Run 已暂停。",
                remaining=max(0, remaining),
            )
        return BudgetReservation(output_limit, estimated_input)
